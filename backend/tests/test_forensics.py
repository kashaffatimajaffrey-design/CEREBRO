"""
Tests for the email forensics module.

These use realistic full-message fixtures — headers included — because the whole
point of the module is that it reads headers. A test that passes a snippet would
be testing nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ml.email.forensics import (  # noqa: E402
    analyze_email, explain_prompt, _levenshtein, _registrable_domain,
    _normalize_homographs, _closest_brand,
)

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

BENIGN = """\
Return-Path: <notifications@github.com>
Received: from smtp.github.com (smtp.github.com [192.30.252.192])
 by mx.example.org with ESMTPS id abc123; Tue, 14 Jul 2026 09:12:04 +0000
Authentication-Results: mx.example.org;
 spf=pass smtp.mailfrom=github.com;
 dkim=pass header.d=github.com;
 dmarc=pass header.from=github.com
DKIM-Signature: v=1; a=rsa-sha256; d=github.com; s=pf2014;
Message-ID: <a1b2c3@github.com>
From: GitHub <notifications@github.com>
To: dev@example.org
Subject: [repo] Pull request #42 merged
Date: Tue, 14 Jul 2026 09:12:00 +0000
Content-Type: text/plain; charset=utf-8

Your pull request #42 was merged into main.
View it at https://github.com/acme/repo/pull/42
"""

PHISH = """\
Return-Path: <bounce@mailer-xyz.ru>
Received: from unknown (10.0.0.5)
 by mx.example.org with SMTP id zzz999; Tue, 14 Jul 2026 03:44:10 +0000
Authentication-Results: mx.example.org;
 spf=fail smtp.mailfrom=mailer-xyz.ru;
 dkim=fail header.d=mailer-xyz.ru;
 dmarc=fail header.from=micros0ft.com
DKIM-Signature: v=1; a=rsa-sha256; d=mailer-xyz.ru; s=k1;
Message-ID: <999@mailer-xyz.ru>
From: "Microsoft 365 Security" <alerts@micros0ft.com>
Reply-To: recovery-desk@protonmail.com
To: victim@example.org
Subject: URGENT: Your account will be suspended within 24 hours
Date: Tue, 14 Jul 2026 03:44:00 +0000
Content-Type: text/html; charset=utf-8

<html><body>
<p>We detected unusual activity. Your account has been locked.</p>
<p>You must verify your account immediately or it will be terminated.</p>
<p><a href="http://192.168.44.9/login">https://login.microsoftonline.com</a></p>
<p><a href="https://bit.ly/3xKq9">Click here to reactivate</a></p>
</body></html>
"""

HOMOGRAPH = """\
Authentication-Results: mx.example.org; spf=pass; dkim=pass header.d=paypa1.com
From: PayPal Service <service@paypa1.com>
To: user@example.org
Subject: Confirm your identity
Content-Type: text/html

<html><body>
<a href="https://раypal.com/verify">Verify your account</a>
</body></html>
"""

NO_AUTH = """\
From: Colleague <colleague@example.org>
To: me@example.org
Subject: Lunch tomorrow?
Content-Type: text/plain

Are you free around 1pm?
"""


# --------------------------------------------------------------------------
# Helper unit tests
# --------------------------------------------------------------------------

def test_levenshtein():
    assert _levenshtein("microsoft", "microsoft") == 0
    assert _levenshtein("micros0ft", "microsoft") == 1
    assert _levenshtein("paypa1", "paypal") == 1
    assert _levenshtein("", "abc") == 3


def test_registrable_domain():
    assert _registrable_domain("mail.google.com") == "google.com"
    assert _registrable_domain("a.b.co.uk") == "b.co.uk"
    assert _registrable_domain("example.com") == "example.com"
    assert _registrable_domain("") == ""


def test_homograph_folding():
    folded, changed = _normalize_homographs("рaypal.com")  # Cyrillic er
    assert changed is True
    assert folded == "paypal.com"
    folded2, changed2 = _normalize_homographs("paypal.com")
    assert changed2 is False


def test_closest_brand_ignores_exact_match():
    # An exact brand match is legitimate use, not typosquatting.
    assert _closest_brand("microsoft.com")[0] is None
    assert _closest_brand("micros0ft.com")[0] == "microsoft"


# --------------------------------------------------------------------------
# End-to-end
# --------------------------------------------------------------------------

def test_benign_message_scores_low():
    r = analyze_email(BENIGN)
    assert r.from_domain == "github.com"
    assert r.spf == "pass"
    assert r.dkim == "pass"
    assert r.dmarc == "pass"
    assert r.dkim_aligned is True
    assert r.heuristic_risk < 0.15, f"benign scored {r.heuristic_risk}"
    codes = {i.code for i in r.indicators}
    assert "DMARC_FAIL" not in codes
    assert "DKIM_MISALIGNED" not in codes


def test_phishing_message_scores_high():
    r = analyze_email(PHISH)
    codes = {i.code for i in r.indicators}

    # Authentication failures
    assert "SPF_FAIL" in codes
    assert "DKIM_FAIL" in codes
    assert "DMARC_FAIL" in codes
    assert r.dkim_aligned is False
    assert "DKIM_MISALIGNED" in codes

    # Identity
    assert "REPLY_TO_MISMATCH" in codes
    assert "LOOKALIKE_SENDER_DOMAIN" in codes   # micros0ft.com vs microsoft

    # URLs
    assert "URL_ANCHOR_MISMATCH" in codes       # text says microsoftonline, href is an IP
    assert "URL_IP_LITERAL" in codes
    assert "URL_SHORTENER" in codes

    # Content
    assert "PRESSURE_LANGUAGE" in codes
    assert "CREDENTIAL_HARVEST_PATTERN" in codes

    assert r.heuristic_risk > 0.90, f"phish scored {r.heuristic_risk}"


def test_homograph_detection():
    r = analyze_email(HOMOGRAPH)
    codes = {i.code for i in r.indicators}
    assert "URL_HOMOGRAPH" in codes
    assert "LOOKALIKE_SENDER_DOMAIN" in codes   # paypa1.com vs paypal
    homo = [u for u in r.urls if u.homograph_of]
    assert homo and homo[0].homograph_of == "paypal.com"


def test_missing_auth_is_low_not_high():
    # Absence of auth headers is common in internal mail; it must not
    # by itself produce a high score. Over-flagging destroys analyst trust.
    r = analyze_email(NO_AUTH)
    codes = {i.code for i in r.indicators}
    assert "NO_AUTH_RESULTS" in codes
    assert r.heuristic_risk < 0.15, f"benign no-auth scored {r.heuristic_risk}"


def test_feature_vector_is_flat_and_numeric():
    r = analyze_email(PHISH)
    assert r.features, "feature vector must not be empty"
    for k, v in r.features.items():
        assert isinstance(v, (int, float)), f"{k} is {type(v)}, must be numeric"
    # Stability: these keys are a model-version contract.
    for required in ("spf_fail", "dkim_aligned", "url_count", "lexicon_hits"):
        assert required in r.features


def test_explanation_prompt_forbids_invention():
    r = analyze_email(PHISH)
    p = explain_prompt(r)
    assert "Do not infer, speculate" in p
    assert "DKIM_MISALIGNED" in p
    assert str(round(r.heuristic_risk, 2)) in p


def test_handles_malformed_input_without_crashing():
    for junk in ("", "not an email at all", "From: \nSubject:\n\n", "\x00\x01"):
        r = analyze_email(junk)
        assert 0.0 <= r.heuristic_risk <= 1.0


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
