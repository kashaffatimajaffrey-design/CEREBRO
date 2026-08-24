"""
Real email forensics — deterministic feature extraction from RFC 5322 messages.

This replaces v1's approach, which sent a ~100-character Gmail *snippet* to an LLM
and asked it to judge "header alignment". No headers were ever sent. The UI's claim
of spoofing detection had nothing behind it.

Everything here is computed from the message itself:
  - SPF / DKIM / DMARC results and, critically, DKIM d= alignment against From:
  - Received-chain structure and timing
  - Display-name vs. envelope-sender spoofing
  - URL extraction, anchor-text mismatch, punycode homographs, brand lookalikes
  - Urgency lexicon density

No model is called. No network request is made (domain age lookup is a separate,
optional async enrichment step). The output is a feature vector plus human-readable
indicators — the classifier consumes the former, the analyst reads the latter.

Design note: every indicator carries a weight and a reason. When a security tool
says "this is phishing", the analyst's next question is always "why" — and
"the model said so" is not an acceptable answer in an incident review.
"""

from __future__ import annotations

import email
import email.policy
import hashlib
import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, getaddresses, parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse, unquote

# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

# Brands most frequently impersonated in credential-harvesting campaigns.
# Kept short and explicit; extend from your own incident data over time.
IMPERSONATED_BRANDS: tuple[str, ...] = (
    "microsoft", "office365", "outlook", "google", "gmail", "apple", "icloud",
    "amazon", "paypal", "netflix", "facebook", "instagram", "linkedin",
    "dropbox", "docusign", "adobe", "chase", "wellsfargo", "bankofamerica",
    "hsbc", "barclays", "dhl", "fedex", "ups", "usps", "irs", "hmrc",
    "coinbase", "binance", "steam", "whatsapp", "zoom", "slack",
)

URL_SHORTENERS: frozenset[str] = frozenset({
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "adf.ly", "bl.ink", "lnkd.in", "rebrand.ly", "cutt.ly", "shorturl.at",
    "rb.gy", "tiny.cc", "s.id", "short.io", "t.ly",
})

# Free mail providers — a "billing department" writing from gmail.com is notable.
FREEMAIL_DOMAINS: frozenset[str] = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "protonmail.com", "mail.com", "gmx.com", "yandex.com", "icloud.com",
})

# Lexicon grouped by pressure tactic. Density matters more than any single hit.
URGENCY_LEXICON: dict[str, tuple[str, ...]] = {
    "time_pressure": (
        "urgent", "immediately", "right away", "asap", "expires today",
        "within 24 hours", "final notice", "last warning", "act now",
        "time sensitive", "deadline", "before it's too late",
    ),
    "threat": (
        "suspended", "terminated", "deactivated", "locked", "disabled",
        "unauthorized access", "security alert", "unusual activity",
        "will be closed", "legal action", "penalty", "fine",
    ),
    "credential_bait": (
        "verify your account", "confirm your identity", "update your password",
        "re-enter your", "validate your", "sign in to continue",
        "confirm your details", "reactivate",
    ),
    "financial_lure": (
        "refund", "you have won", "claim your", "prize", "inheritance",
        "unclaimed funds", "tax rebate", "compensation", "bonus payment",
    ),
    "secrecy": (
        "do not share", "confidential", "keep this between", "discreet",
        "do not tell", "private matter",
    ),
}

# Cyrillic / Greek characters that render like Latin ones. The classic
# homograph attack: "аpple.com" where 'а' is U+0430.
HOMOGRAPH_MAP: dict[str, str] = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "х": "x", "у": "y", "і": "i", "ј": "j", "һ": "h",
    "ο": "o", "α": "a", "ε": "e", "ρ": "p", "υ": "u",
    "ԁ": "d", "ԛ": "q", "ɡ": "g",
}

_URL_RE = re.compile(r"""https?://[^\s<>"'\)\]]+""", re.IGNORECASE)
_HREF_RE = re.compile(
    r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_AUTH_KV_RE = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*(\w+)", re.IGNORECASE)
_DKIM_D_RE = re.compile(r"\bheader\.(?:d|i)\s*=\s*@?([A-Za-z0-9.\-]+)", re.IGNORECASE)


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

@dataclass
class Indicator:
    """A single named finding, with the weight it contributes and why."""
    code: str
    severity: str          # 'info' | 'low' | 'medium' | 'high' | 'critical'
    weight: float          # contribution to the heuristic prior, 0..1
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass
class URLFinding:
    url: str
    domain: str
    anchor_text: str | None = None
    anchor_mismatch: bool = False
    is_punycode: bool = False
    homograph_of: str | None = None
    lookalike_brand: str | None = None
    lookalike_distance: int | None = None
    is_shortener: bool = False
    is_ip_literal: bool = False
    has_credentials: bool = False
    subdomain_depth: int = 0

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ForensicsResult:
    """
    Everything downstream needs:
      - `features` feeds the classifier (LightGBM head alongside RoBERTa logits)
      - `indicators` feeds the analyst UI and the LLM explanation prompt
      - `heuristic_risk` is a transparent prior, NOT the final score
    """
    message_id: str | None
    from_display: str | None
    from_addr: str | None
    from_domain: str | None
    reply_to_addr: str | None
    return_path: str | None
    subject: str | None
    spf: str | None
    dkim: str | None
    dkim_domain: str | None
    dmarc: str | None
    dkim_aligned: bool | None
    urls: list[URLFinding] = field(default_factory=list)
    indicators: list[Indicator] = field(default_factory=list)
    features: dict[str, Any] = field(default_factory=dict)
    heuristic_risk: float = 0.0
    body_text: str = ""
    body_sha256: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "from_display": self.from_display,
            "from_addr": self.from_addr,
            "from_domain": self.from_domain,
            "reply_to_addr": self.reply_to_addr,
            "return_path": self.return_path,
            "subject": self.subject,
            "spf": self.spf,
            "dkim": self.dkim,
            "dkim_domain": self.dkim_domain,
            "dmarc": self.dmarc,
            "dkim_aligned": self.dkim_aligned,
            "urls": [u.as_dict() for u in self.urls],
            "indicators": [i.as_dict() for i in self.indicators],
            "features": self.features,
            "heuristic_risk": self.heuristic_risk,
            "body_sha256": self.body_sha256,
        }


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def _registrable_domain(host: str) -> str:
    """
    Approximate eTLD+1. A real deployment should use the `tldextract` package
    with the Public Suffix List; this handles the common multi-part TLDs so the
    module has no hard dependency for the basic path.
    """
    host = (host or "").lower().strip(".")
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_part_tlds = {
        "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au",
        "co.nz", "co.jp", "co.kr", "com.br", "com.cn", "com.pk", "edu.pk",
        "gov.pk", "co.in", "com.mx", "co.za", "com.sg", "com.tr",
    }
    if ".".join(parts[-2:]) in two_part_tlds and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _levenshtein(a: str, b: str) -> int:
    """Iterative DP, O(len(a)*len(b)) time and O(min) space."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,        # deletion
                current[j - 1] + 1,     # insertion
                previous[j - 1] + (ca != cb),  # substitution
            ))
        previous = current
    return previous[-1]


def _normalize_homographs(s: str) -> tuple[str, bool]:
    """Fold confusable Unicode to Latin. Returns (folded, any_substitution_made)."""
    out: list[str] = []
    changed = False
    for ch in s:
        repl = HOMOGRAPH_MAP.get(ch)
        if repl is not None:
            out.append(repl)
            changed = True
        else:
            out.append(ch)
    return "".join(out), changed


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _closest_brand(domain: str) -> tuple[str | None, int | None]:
    """
    Nearest impersonated brand by edit distance on the domain label.
    An exact match is legitimate use, not impersonation — we only care about
    *near* misses (distance 1-2), which is how typosquats work.
    """
    label = _registrable_domain(domain).split(".")[0]
    if not label:
        return None, None
    best, best_d = None, None
    for brand in IMPERSONATED_BRANDS:
        d = _levenshtein(label, brand)
        if best_d is None or d < best_d:
            best, best_d = brand, d
    if best_d is not None and 1 <= best_d <= 2 and len(label) >= 4:
        return best, best_d
    return None, None


# --------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------

def _parse_auth_results(msg: EmailMessage) -> dict[str, Any]:
    """
    Pull SPF/DKIM/DMARC from Authentication-Results (RFC 8601) and
    Received-SPF. Multiple headers may be present; the *first* is the one
    added by the receiving MTA closest to us and is the one to trust.
    """
    result: dict[str, Any] = {
        "spf": None, "dkim": None, "dmarc": None, "dkim_domain": None,
    }

    auth_headers = msg.get_all("Authentication-Results") or []
    for raw in auth_headers:
        raw_str = str(raw)
        for method, verdict in _AUTH_KV_RE.findall(raw_str):
            key = method.lower()
            if result.get(key) is None:
                result[key] = verdict.lower()
        if result["dkim_domain"] is None:
            m = _DKIM_D_RE.search(raw_str)
            if m:
                result["dkim_domain"] = m.group(1).lower()

    if result["spf"] is None:
        for raw in (msg.get_all("Received-SPF") or []):
            token = str(raw).strip().split(None, 1)[0].lower()
            if token in {"pass", "fail", "softfail", "neutral", "none",
                         "temperror", "permerror"}:
                result["spf"] = token
                break

    # Fall back to the DKIM-Signature header's own d= tag.
    if result["dkim_domain"] is None:
        sig = msg.get("DKIM-Signature")
        if sig:
            m = re.search(r"\bd\s*=\s*([A-Za-z0-9.\-]+)", str(sig))
            if m:
                result["dkim_domain"] = m.group(1).lower()

    return result


def _analyze_received_chain(msg: EmailMessage) -> dict[str, Any]:
    """
    The Received chain is written bottom-up: index 0 is the last hop
    (closest to us). Large timing gaps and private-IP leakage are both
    worth surfacing, though neither is conclusive alone.
    """
    received = [str(h) for h in (msg.get_all("Received") or [])]
    info: dict[str, Any] = {
        "hop_count": len(received),
        "max_gap_seconds": None,
        "private_ip_hops": 0,
        "parse_failures": 0,
    }

    timestamps: list[datetime] = []
    for hop in received:
        # The timestamp follows the final ';' in a Received header.
        if ";" in hop:
            try:
                ts = parsedate_to_datetime(hop.rsplit(";", 1)[1].strip())
                if ts is not None:
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    timestamps.append(ts)
            except (TypeError, ValueError, IndexError):
                info["parse_failures"] += 1

        for ip_str in re.findall(r"\[?(\d{1,3}(?:\.\d{1,3}){3})\]?", hop):
            try:
                if ipaddress.ip_address(ip_str).is_private:
                    info["private_ip_hops"] += 1
            except ValueError:
                pass

    if len(timestamps) >= 2:
        timestamps.sort()
        gaps = [(b - a).total_seconds()
                for a, b in zip(timestamps, timestamps[1:])]
        info["max_gap_seconds"] = max(gaps) if gaps else None

    return info


def _decode_part(part: EmailMessage) -> str:
    """
    Decode a message part to text without losing non-ASCII characters.

    We deliberately do NOT trust `get_content()` alone. When a part declares no
    charset, the RFC default is us-ascii, and the stdlib will replace every
    non-ASCII byte with U+FFFD. Phishing messages routinely omit the charset —
    and the characters that get destroyed are exactly the Cyrillic homographs
    we need to detect. So: decode the raw bytes, trying the declared charset
    first and falling back through the common ones.
    """
    blob = part.get_payload(decode=True)
    if blob is None:
        try:
            content = part.get_content()
            return content if isinstance(content, str) else str(content)
        except (LookupError, ValueError, KeyError, AttributeError):
            payload = part.get_payload()
            return payload if isinstance(payload, str) else ""

    declared = part.get_content_charset()
    candidates = [c for c in (declared, "utf-8", "cp1252", "latin-1") if c]
    for charset in candidates:
        try:
            return blob.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue
    return blob.decode("utf-8", errors="replace")


def _extract_bodies(msg: EmailMessage) -> tuple[str, str]:
    """Return (plain_text, html). Handles multipart and single-part messages."""
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            if part.get_filename():          # attachment, not body
                continue
            ctype = part.get_content_type()
            payload = _decode_part(part)     # type: ignore[arg-type]
            if ctype == "text/plain":
                plain_parts.append(payload)
            elif ctype == "text/html":
                html_parts.append(payload)
    else:
        payload = _decode_part(msg)
        if msg.get_content_type() == "text/html":
            html_parts.append(payload)
        else:
            plain_parts.append(payload)

    return "\n".join(plain_parts), "\n".join(html_parts)


def _extract_attachments(msg: EmailMessage) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not msg.is_multipart():
        return out
    for part in msg.walk():
        fname = part.get_filename()
        if not fname:
            continue
        data = part.get_payload(decode=True) or b""
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
        out.append({
            "filename": fname,
            "content_type": part.get_content_type(),
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest() if data else None,
            "extension": ext,
        })
    return out


# --------------------------------------------------------------------------
# URL analysis
# --------------------------------------------------------------------------

DANGEROUS_EXTENSIONS = frozenset({
    "exe", "scr", "com", "pif", "bat", "cmd", "js", "jse", "vbs", "vbe",
    "wsf", "wsh", "hta", "jar", "msi", "ps1", "lnk", "iso", "img", "reg",
})
MACRO_EXTENSIONS = frozenset({"docm", "xlsm", "pptm", "dotm", "xltm"})


def _analyze_urls(plain: str, html: str) -> list[URLFinding]:
    findings: list[URLFinding] = []
    seen: set[str] = set()

    def add(url: str, anchor: str | None) -> None:
        url = url.strip().rstrip(".,;)")
        if not url or url in seen:
            return
        seen.add(url)

        try:
            parsed = urlparse(url)
        except ValueError:
            return
        host = (parsed.hostname or "").lower()
        if not host:
            return

        folded, had_homograph = _normalize_homographs(host)
        is_puny = host.startswith("xn--") or ".xn--" in host
        is_ip = _is_ip_literal(host)
        # eTLD+1 logic is meaningless for an IP literal — "192.168.44.9" would
        # reduce to "44.9". Keep the address itself as the identifier.
        brand, dist = (None, None) if is_ip else _closest_brand(host)

        f = URLFinding(
            url=url,
            domain=host if is_ip else _registrable_domain(host),
            anchor_text=anchor,
            is_punycode=is_puny,
            homograph_of=_registrable_domain(folded) if had_homograph else None,
            lookalike_brand=brand,
            lookalike_distance=dist,
            is_shortener=_registrable_domain(host) in URL_SHORTENERS,
            is_ip_literal=is_ip,
            has_credentials="@" in (parsed.netloc or ""),
            subdomain_depth=max(0, host.count(".") - 1),
        )

        # Anchor text that looks like a domain but points elsewhere.
        if anchor:
            anchor_clean = _TAG_RE.sub("", anchor).strip()
            m = re.search(r"\b([a-z0-9\-]+\.[a-z]{2,})\b", anchor_clean, re.I)
            if m:
                claimed = _registrable_domain(m.group(1))
                if claimed and claimed != f.domain:
                    f.anchor_mismatch = True

        findings.append(f)

    for href, anchor in _HREF_RE.findall(html or ""):
        add(unquote(href), anchor)
    for url in _URL_RE.findall(plain or ""):
        add(url, None)
    # Bare URLs in HTML that weren't inside an <a> tag.
    for url in _URL_RE.findall(_TAG_RE.sub(" ", html or "")):
        add(url, None)

    return findings


def _lexicon_hits(text: str) -> dict[str, list[str]]:
    lowered = (text or "").lower()
    hits: dict[str, list[str]] = {}
    for category, phrases in URGENCY_LEXICON.items():
        found = [p for p in phrases if p in lowered]
        if found:
            hits[category] = found
    return hits


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def analyze_email(raw: str | bytes) -> ForensicsResult:
    """
    Parse a full RFC 5322 message and extract every deterministic signal.

    Args:
        raw: the complete message source — headers AND body. Passing a snippet
             here defeats the purpose; fetch Gmail messages with format='raw'.

    Returns:
        ForensicsResult with a feature dict ready for the classifier.
    """
    # Always parse from bytes. Parsing from str routes non-ASCII payloads through
    # raw-unicode-escape, which silently turns a Cyrillic homograph into the
    # literal text "р" — destroying the exact signal we are looking for.
    # Mail is bytes on the wire; treat it that way.
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="surrogateescape")
    msg: EmailMessage = email.message_from_bytes(raw, policy=email.policy.default)  # type: ignore[assignment]

    # ---- identity headers -------------------------------------------------
    from_display, from_addr = parseaddr(str(msg.get("From", "")))
    from_domain = _registrable_domain(from_addr.split("@")[-1]) if "@" in from_addr else None

    reply_to_pairs = getaddresses([str(h) for h in (msg.get_all("Reply-To") or [])])
    reply_to_addr = reply_to_pairs[0][1] if reply_to_pairs else None
    reply_to_domain = (
        _registrable_domain(reply_to_addr.split("@")[-1])
        if reply_to_addr and "@" in reply_to_addr else None
    )

    _, return_path = parseaddr(str(msg.get("Return-Path", "")))
    return_path_domain = (
        _registrable_domain(return_path.split("@")[-1])
        if return_path and "@" in return_path else None
    )

    subject = str(msg.get("Subject", "")) or None
    message_id = str(msg.get("Message-ID", "")) or None

    # ---- authentication ---------------------------------------------------
    auth = _parse_auth_results(msg)
    dkim_domain = auth["dkim_domain"]
    dkim_aligned: bool | None = None
    if dkim_domain and from_domain:
        dkim_aligned = _registrable_domain(dkim_domain) == from_domain

    chain = _analyze_received_chain(msg)

    # ---- content ----------------------------------------------------------
    plain, html = _extract_bodies(msg)
    body_text = plain or _TAG_RE.sub(" ", html)
    body_text = re.sub(r"\s+", " ", body_text).strip()
    urls = _analyze_urls(plain, html)
    attachments = _extract_attachments(msg)
    lexicon = _lexicon_hits(f"{subject or ''} {body_text}")

    result = ForensicsResult(
        message_id=message_id,
        from_display=from_display or None,
        from_addr=from_addr or None,
        from_domain=from_domain,
        reply_to_addr=reply_to_addr,
        return_path=return_path or None,
        subject=subject,
        spf=auth["spf"],
        dkim=auth["dkim"],
        dkim_domain=dkim_domain,
        dmarc=auth["dmarc"],
        dkim_aligned=dkim_aligned,
        urls=urls,
        body_text=body_text,
        body_sha256=hashlib.sha256(body_text.encode()).hexdigest() if body_text else None,
    )

    ind = result.indicators

    # ---- authentication indicators ---------------------------------------
    if auth["spf"] in {"fail", "softfail"}:
        ind.append(Indicator(
            "SPF_FAIL", "high", 0.25,
            f"SPF {auth['spf']}: the sending server is not authorized to send "
            f"for {from_domain or 'the From domain'}."))
    if auth["dkim"] == "fail":
        ind.append(Indicator(
            "DKIM_FAIL", "high", 0.25,
            "DKIM signature failed validation — the message was altered in "
            "transit or forged."))
    if auth["dmarc"] == "fail":
        ind.append(Indicator(
            "DMARC_FAIL", "critical", 0.35,
            "DMARC failed. The domain owner's published policy says this "
            "message should not be trusted."))
    if dkim_aligned is False:
        ind.append(Indicator(
            "DKIM_MISALIGNED", "critical", 0.35,
            f"DKIM signed by '{dkim_domain}' but the message claims to be from "
            f"'{from_domain}'. This is the classic signature of a spoofed sender."))
    if not any([auth["spf"], auth["dkim"], auth["dmarc"]]):
        ind.append(Indicator(
            "NO_AUTH_RESULTS", "low", 0.05,
            "No authentication results present — cannot verify sender. "
            "Common for internally-relayed or archived mail."))

    # ---- identity / spoofing indicators ----------------------------------
    if from_display:
        m = re.search(r"\b([a-z0-9\-]+\.[a-z]{2,})\b", from_display, re.I)
        if m:
            claimed = _registrable_domain(m.group(1))
            if from_domain and claimed and claimed != from_domain:
                ind.append(Indicator(
                    "DISPLAY_NAME_SPOOF", "high", 0.25,
                    f"Display name references '{claimed}' but the actual sender "
                    f"domain is '{from_domain}'."))
        for brand in IMPERSONATED_BRANDS:
            if brand in from_display.lower() and from_domain:
                if brand not in from_domain and from_domain in FREEMAIL_DOMAINS:
                    ind.append(Indicator(
                        "BRAND_FROM_FREEMAIL", "high", 0.30,
                        f"Claims to be '{brand}' but sends from the free mail "
                        f"provider '{from_domain}'."))
                break

    if reply_to_domain and from_domain and reply_to_domain != from_domain:
        ind.append(Indicator(
            "REPLY_TO_MISMATCH", "medium", 0.18,
            f"Replies would go to '{reply_to_domain}', not the apparent sender "
            f"'{from_domain}'."))

    if return_path_domain and from_domain and return_path_domain != from_domain:
        ind.append(Indicator(
            "RETURN_PATH_MISMATCH", "medium", 0.12,
            f"Envelope sender '{return_path_domain}' differs from header From "
            f"'{from_domain}'. Normal for mailing lists, suspicious otherwise."))

    if from_domain:
        brand, dist = _closest_brand(from_domain)
        if brand:
            ind.append(Indicator(
                "LOOKALIKE_SENDER_DOMAIN", "critical", 0.35,
                f"Sender domain '{from_domain}' is {dist} character(s) from "
                f"'{brand}' — likely typosquatting."))

    # ---- URL indicators ---------------------------------------------------
    for u in urls:
        if u.anchor_mismatch:
            ind.append(Indicator(
                "URL_ANCHOR_MISMATCH", "high", 0.25,
                f"Link text points at a different domain than the actual "
                f"destination '{u.domain}'."))
        if u.is_punycode or u.homograph_of:
            ind.append(Indicator(
                "URL_HOMOGRAPH", "critical", 0.35,
                f"'{u.domain}' uses characters that visually imitate "
                f"'{u.homograph_of or 'a Latin domain'}'."))
        if u.lookalike_brand:
            ind.append(Indicator(
                "URL_LOOKALIKE", "high", 0.28,
                f"Link domain '{u.domain}' is {u.lookalike_distance} "
                f"character(s) from '{u.lookalike_brand}'."))
        if u.is_ip_literal:
            ind.append(Indicator(
                "URL_IP_LITERAL", "high", 0.22,
                f"Link points directly at an IP address ({u.url}) rather than "
                f"a domain name."))
        if u.has_credentials:
            ind.append(Indicator(
                "URL_EMBEDDED_CREDENTIALS", "high", 0.25,
                "URL contains an '@' before the host — a classic technique for "
                "disguising the real destination."))
        if u.is_shortener:
            ind.append(Indicator(
                "URL_SHORTENER", "medium", 0.12,
                f"Shortened link ({u.domain}) conceals its destination."))
        if u.subdomain_depth >= 4:
            ind.append(Indicator(
                "URL_DEEP_SUBDOMAIN", "medium", 0.10,
                f"Unusually deep subdomain nesting in '{u.url}' — often used to "
                f"push the real domain out of view on mobile clients."))

    # ---- attachment indicators -------------------------------------------
    for a in attachments:
        if a["extension"] in DANGEROUS_EXTENSIONS:
            ind.append(Indicator(
                "DANGEROUS_ATTACHMENT", "critical", 0.40,
                f"Executable attachment '{a['filename']}'."))
        elif a["extension"] in MACRO_EXTENSIONS:
            ind.append(Indicator(
                "MACRO_ATTACHMENT", "high", 0.25,
                f"Macro-enabled document '{a['filename']}'."))

    # ---- content indicators ----------------------------------------------
    total_lexicon_hits = sum(len(v) for v in lexicon.values())
    if len(lexicon) >= 2:
        ind.append(Indicator(
            "PRESSURE_LANGUAGE", "medium",
            min(0.20, 0.06 * len(lexicon)),
            "Message combines multiple manipulation tactics: "
            + ", ".join(lexicon.keys()) + "."))
    if "credential_bait" in lexicon and urls:
        ind.append(Indicator(
            "CREDENTIAL_HARVEST_PATTERN", "high", 0.25,
            "Asks the recipient to verify credentials and provides a link — "
            "the standard credential-harvesting structure."))

    if chain["private_ip_hops"] > 0 and chain["hop_count"] > 1:
        ind.append(Indicator(
            "PRIVATE_IP_IN_CHAIN", "info", 0.02,
            f"{chain['private_ip_hops']} hop(s) reference private IP space."))

    # ---- feature vector ---------------------------------------------------
    # This is what the model consumes. Keep it flat, numeric, and stable —
    # adding a key is a model-version change.
    result.features = {
        # authentication
        "spf_pass": int(auth["spf"] == "pass"),
        "spf_fail": int(auth["spf"] in {"fail", "softfail"}),
        "dkim_pass": int(auth["dkim"] == "pass"),
        "dkim_fail": int(auth["dkim"] == "fail"),
        "dmarc_pass": int(auth["dmarc"] == "pass"),
        "dmarc_fail": int(auth["dmarc"] == "fail"),
        "dkim_aligned": int(bool(dkim_aligned)),
        "auth_present": int(any([auth["spf"], auth["dkim"], auth["dmarc"]])),
        # identity
        "reply_to_mismatch": int(bool(
            reply_to_domain and from_domain and reply_to_domain != from_domain)),
        "return_path_mismatch": int(bool(
            return_path_domain and from_domain and return_path_domain != from_domain)),
        "from_is_freemail": int(bool(from_domain in FREEMAIL_DOMAINS)),
        "from_lookalike": int(bool(from_domain and _closest_brand(from_domain)[0])),
        "display_name_len": len(from_display or ""),
        # routing
        "hop_count": chain["hop_count"],
        "private_ip_hops": chain["private_ip_hops"],
        "max_hop_gap_seconds": chain["max_gap_seconds"] or 0.0,
        # urls
        "url_count": len(urls),
        "url_unique_domains": len({u.domain for u in urls}),
        "url_anchor_mismatches": sum(u.anchor_mismatch for u in urls),
        "url_punycode": sum(u.is_punycode or bool(u.homograph_of) for u in urls),
        "url_lookalikes": sum(bool(u.lookalike_brand) for u in urls),
        "url_shorteners": sum(u.is_shortener for u in urls),
        "url_ip_literals": sum(u.is_ip_literal for u in urls),
        "url_max_subdomain_depth": max((u.subdomain_depth for u in urls), default=0),
        # attachments
        "attachment_count": len(attachments),
        "dangerous_attachments": sum(
            a["extension"] in DANGEROUS_EXTENSIONS for a in attachments),
        "macro_attachments": sum(
            a["extension"] in MACRO_EXTENSIONS for a in attachments),
        # content
        "body_length": len(body_text),
        "subject_length": len(subject or ""),
        "lexicon_categories": len(lexicon),
        "lexicon_hits": total_lexicon_hits,
        "has_html": int(bool(html)),
        "html_to_text_ratio": (len(html) / max(1, len(plain))) if plain else float(bool(html)),
        "subject_is_reply": int(bool(subject and subject.lower().startswith(("re:", "fwd:")))),
    }

    # ---- transparent heuristic prior --------------------------------------
    # Deliberately NOT the final answer. It is a cold-start baseline and a
    # sanity check on the learned model: if they disagree wildly, investigate.
    # Combined so that many weak signals cannot alone reach certainty.
    risk = 0.0
    for i in ind:
        risk = risk + i.weight * (1.0 - risk)
    result.heuristic_risk = round(min(risk, 0.99), 4)

    return result


def explain_prompt(result: ForensicsResult) -> str:
    """
    Build the LLM prompt for the analyst-facing narrative.

    Note what is and isn't here: the model is given the ALREADY-COMPUTED
    findings and asked to write them up. It is explicitly forbidden from
    inventing new ones. This is the correct division of labour — deterministic
    code decides, the language model communicates.
    """
    lines = [
        "You are writing an incident note for a security analyst.",
        "Summarize ONLY the findings listed below. Do not infer, speculate, or "
        "add indicators that are not present. If the findings are weak, say so.",
        "",
        f"Sender: {result.from_display or '(none)'} <{result.from_addr or 'unknown'}>",
        f"Subject: {result.subject or '(none)'}",
        f"SPF={result.spf or 'n/a'} DKIM={result.dkim or 'n/a'} "
        f"DMARC={result.dmarc or 'n/a'} DKIM-aligned={result.dkim_aligned}",
        "",
        "Findings:",
    ]
    if result.indicators:
        for i in sorted(result.indicators, key=lambda x: -x.weight):
            lines.append(f"  [{i.severity.upper()}] {i.code}: {i.detail}")
    else:
        lines.append("  (none — no deterministic risk signals were found)")
    lines += [
        "",
        f"Heuristic prior: {result.heuristic_risk:.2f}",
        "",
        "Write 2-4 sentences: what this message appears to be, the strongest "
        "evidence for that read, and the recommended action.",
    ]
    return "\n".join(lines)
