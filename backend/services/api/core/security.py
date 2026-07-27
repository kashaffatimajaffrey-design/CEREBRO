"""
Authentication and secrets handling.

Replaces two things from v1:

  1. `services/authService.ts`, which stored passwords in plaintext in
     localStorage and compared them with `u.password === password`.
  2. `localStorage.setItem('cerebro_gmail_token', accessToken)` — an OAuth token
     carrying gmail.send scope, readable by any XSS on the origin.

Design decisions worth stating:

- **scrypt, not bcrypt or a bare hash.** scrypt is memory-hard (resists GPU and
  ASIC attack) and lives in the Python standard library, so there is no
  dependency to install, pin, or have go unmaintained. Argon2id is marginally
  preferable if you are willing to take the dependency; the parameters below
  target roughly the same work factor.

- **Tokens are encrypted at rest with AES-256-GCM.** A database dump must not
  hand the attacker live access to every user's mailbox. GCM is authenticated,
  so tampering is detected rather than silently decrypted into garbage.

- **Refresh tokens are stored as SHA-256 hashes.** Same reasoning as passwords:
  the server never needs the original, so it should not keep it.

- **Every comparison is constant-time.** `==` on a secret leaks length and
  prefix information through timing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# --- password hashing -------------------------------------------------------

# n=2^15 costs ~64 MB and ~100 ms per hash on typical hardware. High enough to
# make offline cracking expensive, low enough not to become a login DoS vector.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return `scrypt$n$r$p$<salt_b64>$<hash_b64>`."""
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
        maxmem=128 * _SCRYPT_N * _SCRYPT_R * 2,
    )
    return "$".join([
        "scrypt", str(_SCRYPT_N), str(_SCRYPT_R), str(_SCRYPT_P),
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode(),
    ])


def verify_password(password: str, stored: str) -> bool:
    """
    Constant-time verification. Returns False on any malformed hash rather than
    raising — an attacker should not be able to distinguish "bad password" from
    "corrupt record" by the error they get back.
    """
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError, base64.binascii.Error):  # type: ignore[attr-defined]
        return False

    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=128 * n * r * 2,
        )
    except (ValueError, MemoryError):
        return False

    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str) -> bool:
    """True when a stored hash used weaker parameters than we now require."""
    try:
        scheme, n_s, r_s, p_s, _, _ = stored.split("$")
        return scheme != "scrypt" or int(n_s) < _SCRYPT_N or int(r_s) < _SCRYPT_R
    except ValueError:
        return True


# --- opaque tokens ----------------------------------------------------------

def generate_token(nbytes: int = 32) -> str:
    """Cryptographically secure, URL-safe. Used for refresh tokens and API keys."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """
    SHA-256 for token lookup. Unlike passwords this is a fast hash on purpose:
    tokens are already high-entropy random, so there is nothing to brute-force,
    and the lookup happens on every authenticated request.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# --- JWT access tokens ------------------------------------------------------

class TokenError(Exception):
    """Raised for any invalid, expired, or tampered token."""


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_access_token(
    *, user_id: str, tenant_id: str, role: str, secret: str,
    ttl_minutes: int = 60, extra: dict[str, Any] | None = None,
) -> str:
    """
    HS256 JWT carrying the tenant. Written against the stdlib rather than PyJWT
    so the auth path has no third-party dependency — one less thing that can
    break a deployment or ship a CVE.

    `tid` is in the token because every RLS policy keys off it; the API sets
    `app.tenant_id` from this claim on each request.
    """
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user_id,
        "tid": tenant_id,
        "role": role,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_minutes * 60,
        "jti": secrets.token_urlsafe(8),
    }
    if extra:
        payload.update(extra)

    signing_input = ".".join([
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode()),
        _b64url_encode(json.dumps(payload, separators=(",", ":")).encode()),
    ])
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def decode_access_token(token: str, secret: str, *, leeway_seconds: int = 0) -> dict[str, Any]:
    """
    Verify and decode. Raises TokenError on anything suspicious.

    Note the explicit algorithm check: accepting the token's own `alg` header is
    the classic JWT vulnerability (an attacker sets `alg: none` and signs
    nothing). We ignore what the token claims and require HS256.
    """
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise TokenError("malformed token") from exc

    try:
        header = json.loads(_b64url_decode(header_b64))
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed header") from exc

    if header.get("alg") != "HS256":
        raise TokenError(f"unsupported algorithm: {header.get('alg')!r}")

    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    try:
        provided = _b64url_decode(signature_b64)
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed signature") from exc

    if not hmac.compare_digest(expected, provided):
        raise TokenError("signature verification failed")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, TypeError) as exc:
        raise TokenError("malformed payload") from exc

    now = int(time.time())
    if "exp" in payload and now > payload["exp"] + leeway_seconds:
        raise TokenError("token expired")
    if "nbf" in payload and now < payload["nbf"] - leeway_seconds:
        raise TokenError("token not yet valid")
    for claim in ("sub", "tid"):
        if claim not in payload:
            raise TokenError(f"missing required claim: {claim}")

    return payload


# --- OAuth token encryption at rest -----------------------------------------

@dataclass
class EncryptedBlob:
    nonce: bytes
    ciphertext: bytes

    def to_bytes(self) -> bytes:
        return self.nonce + self.ciphertext

    @classmethod
    def from_bytes(cls, blob: bytes) -> "EncryptedBlob":
        if len(blob) < 13:
            raise ValueError("blob too short to contain a nonce")
        return cls(nonce=blob[:12], ciphertext=blob[12:])


class TokenVault:
    """
    AES-256-GCM encryption for OAuth tokens at rest.

    Uses `cryptography` when available. Falls back to a ChaCha20-style stream
    built on HMAC-SHA256 with an explicit authentication tag — not as fast, but
    stdlib-only, authenticated, and vastly better than storing plaintext.

    The `aad` parameter binds each ciphertext to its owner. A row copied from
    one user to another fails authentication instead of decrypting, which
    prevents a database-level privilege escalation.
    """

    def __init__(self, key: bytes | str | None = None) -> None:
        if key is None:
            key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        if isinstance(key, str):
            key = key.encode() if key else b""
        if not key:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is required to store OAuth tokens. "
                "Generate one with: python -c \"import secrets;"
                "print(secrets.token_urlsafe(32))\""
            )
        # Normalize any input length to exactly 32 bytes.
        self._key = hashlib.sha256(key).digest()

        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            self._aesgcm = AESGCM(self._key)
            self.backend = "aes-gcm"
        except ImportError:
            self._aesgcm = None
            self.backend = "hmac-stream"

    def encrypt(self, plaintext: str, aad: str = "") -> bytes:
        nonce = secrets.token_bytes(12)
        data = plaintext.encode("utf-8")
        if self._aesgcm is not None:
            ct = self._aesgcm.encrypt(nonce, data, aad.encode() or None)
        else:
            ct = self._fallback_seal(nonce, data, aad.encode())
        return EncryptedBlob(nonce, ct).to_bytes()

    def decrypt(self, blob: bytes, aad: str = "") -> str:
        parts = EncryptedBlob.from_bytes(blob)
        if self._aesgcm is not None:
            data = self._aesgcm.decrypt(parts.nonce, parts.ciphertext, aad.encode() or None)
        else:
            data = self._fallback_open(parts.nonce, parts.ciphertext, aad.encode())
        return data.decode("utf-8")

    # -- stdlib fallback ----------------------------------------------------

    def _keystream(self, nonce: bytes, length: int) -> bytes:
        """HMAC-SHA256 in counter mode."""
        out = bytearray()
        counter = 0
        while len(out) < length:
            out += hmac.new(self._key, nonce + counter.to_bytes(4, "big"),
                            hashlib.sha256).digest()
            counter += 1
        return bytes(out[:length])

    def _fallback_seal(self, nonce: bytes, data: bytes, aad: bytes) -> bytes:
        ct = bytes(a ^ b for a, b in zip(data, self._keystream(nonce, len(data))))
        # Encrypt-then-MAC over nonce, aad and ciphertext.
        tag = hmac.new(self._key, b"tag" + nonce + aad + ct, hashlib.sha256).digest()
        return ct + tag

    def _fallback_open(self, nonce: bytes, blob: bytes, aad: bytes) -> bytes:
        if len(blob) < 32:
            raise ValueError("ciphertext too short")
        ct, tag = blob[:-32], blob[-32:]
        expected = hmac.new(self._key, b"tag" + nonce + aad + ct, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, tag):
            raise ValueError("authentication failed: ciphertext was tampered with")
        return bytes(a ^ b for a, b in zip(ct, self._keystream(nonce, len(ct))))


# --- API keys ---------------------------------------------------------------

API_KEY_PREFIX = "crb_"


def generate_api_key() -> tuple[str, str]:
    """
    Returns (plaintext, hash). The plaintext is shown to the user exactly once;
    only the hash is stored. The prefix makes keys greppable in logs and
    recognisable by secret scanners.
    """
    key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return key, hash_token(key)


def session_expiry(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)
