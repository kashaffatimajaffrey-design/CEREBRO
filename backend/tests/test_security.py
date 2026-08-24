"""
Security tests. These are adversarial on purpose — each one is an attack that
worked against v1, or a classic attack against this class of code.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.core.security import (  # noqa: E402
    hash_password, verify_password, needs_rehash,
    generate_token, hash_token, constant_time_compare,
    create_access_token, decode_access_token, TokenError,
    TokenVault, generate_api_key, API_KEY_PREFIX,
    _b64url_encode, _b64url_decode,
)
import json  # noqa: E402

SECRET = "test-secret-key-at-least-32-characters-long!!"


# --- passwords -------------------------------------------------------------

def test_password_roundtrip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password", h)


def test_password_never_stored_in_plaintext():
    """The v1 failure mode: `{ id, name, email, password }` written to storage."""
    pw = "SuperSecret123!"
    h = hash_password(pw)
    assert pw not in h
    assert pw.encode().hex() not in h
    assert h.startswith("scrypt$")


def test_same_password_gives_different_hashes():
    """Per-password salt: identical passwords must not produce identical rows."""
    a, b = hash_password("identical"), hash_password("identical")
    assert a != b
    assert verify_password("identical", a)
    assert verify_password("identical", b)


def test_short_password_rejected():
    for bad in ("", "a", "1234567"):
        try:
            hash_password(bad)
            raise AssertionError(f"accepted weak password {bad!r}")
        except ValueError:
            pass


def test_malformed_hash_returns_false_not_exception():
    for junk in ("", "garbage", "scrypt$bad", "bcrypt$1$2$3$4$5", "$$$$$"):
        assert verify_password("anything", junk) is False


def test_needs_rehash_detects_weak_params():
    assert needs_rehash("md5$deadbeef") is True
    assert needs_rehash("scrypt$1024$8$1$c2FsdA==$aGFzaA==") is True   # n too low
    assert needs_rehash(hash_password("a valid password")) is False


# --- tokens ----------------------------------------------------------------

def test_token_hashing_is_one_way():
    tok = generate_token()
    h = hash_token(tok)
    assert tok not in h
    assert len(h) == 64
    assert hash_token(tok) == h           # deterministic
    assert hash_token(generate_token()) != h


def test_generated_tokens_are_unique():
    assert len({generate_token() for _ in range(500)}) == 500


def test_constant_time_compare():
    assert constant_time_compare("abc", "abc")
    assert not constant_time_compare("abc", "abd")
    assert not constant_time_compare("abc", "abcd")


# --- JWT -------------------------------------------------------------------

def test_jwt_roundtrip_carries_tenant():
    t = create_access_token(user_id="u1", tenant_id="t1", role="analyst", secret=SECRET)
    payload = decode_access_token(t, SECRET)
    assert payload["sub"] == "u1"
    assert payload["tid"] == "t1"          # RLS depends on this claim
    assert payload["role"] == "analyst"


def test_jwt_rejects_wrong_secret():
    t = create_access_token(user_id="u1", tenant_id="t1", role="analyst", secret=SECRET)
    try:
        decode_access_token(t, "a-completely-different-secret-value-here")
        raise AssertionError("accepted a token signed with another secret")
    except TokenError as exc:
        assert "signature" in str(exc)


def test_jwt_rejects_alg_none_attack():
    """
    The classic JWT vulnerability: attacker rewrites the header to alg=none and
    strips the signature. A decoder that trusts the token's own alg accepts it.
    """
    header = _b64url_encode(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps(
        {"sub": "attacker", "tid": "victim-tenant", "role": "owner",
         "exp": int(time.time()) + 3600}).encode())
    forged = f"{header}.{payload}."
    try:
        decode_access_token(forged, SECRET)
        raise AssertionError("SECURITY FAILURE: accepted alg=none token")
    except TokenError as exc:
        assert "algorithm" in str(exc)


def test_jwt_rejects_tampered_payload():
    """Escalate role from analyst to owner without re-signing."""
    t = create_access_token(user_id="u1", tenant_id="t1", role="analyst", secret=SECRET)
    h, p, s = t.split(".")
    payload = json.loads(_b64url_decode(p))
    payload["role"] = "owner"
    forged = f"{h}.{_b64url_encode(json.dumps(payload).encode())}.{s}"
    try:
        decode_access_token(forged, SECRET)
        raise AssertionError("SECURITY FAILURE: accepted tampered payload")
    except TokenError:
        pass


def test_jwt_rejects_cross_tenant_swap():
    """Repointing a valid token at another tenant must invalidate the signature."""
    t = create_access_token(user_id="u1", tenant_id="tenant-A", role="analyst", secret=SECRET)
    h, p, s = t.split(".")
    payload = json.loads(_b64url_decode(p))
    payload["tid"] = "tenant-B"
    forged = f"{h}.{_b64url_encode(json.dumps(payload).encode())}.{s}"
    try:
        decode_access_token(forged, SECRET)
        raise AssertionError("SECURITY FAILURE: accepted cross-tenant token")
    except TokenError:
        pass


def test_jwt_expiry_enforced():
    t = create_access_token(user_id="u1", tenant_id="t1", role="analyst",
                            secret=SECRET, ttl_minutes=-1)
    try:
        decode_access_token(t, SECRET)
        raise AssertionError("accepted an expired token")
    except TokenError as exc:
        assert "expired" in str(exc)


def test_jwt_rejects_malformed():
    for junk in ("", "a", "a.b", "a.b.c.d", "...", "not-a-token"):
        try:
            decode_access_token(junk, SECRET)
            raise AssertionError(f"accepted malformed token {junk!r}")
        except TokenError:
            pass


# --- OAuth token vault -----------------------------------------------------

def test_vault_roundtrip():
    v = TokenVault(key="a-test-encryption-key-value-here")
    token = "ya29.a0AfH6SMBexample-gmail-access-token"
    blob = v.encrypt(token, aad="user-123")
    assert v.decrypt(blob, aad="user-123") == token


def test_vault_ciphertext_does_not_contain_plaintext():
    """A database dump must not reveal live mailbox tokens."""
    v = TokenVault(key="a-test-encryption-key-value-here")
    token = "ya29.SENSITIVE-GMAIL-TOKEN"
    blob = v.encrypt(token, aad="user-123")
    assert token.encode() not in blob
    assert b"SENSITIVE" not in blob


def test_vault_detects_tampering():
    v = TokenVault(key="a-test-encryption-key-value-here")
    blob = bytearray(v.encrypt("secret-token", aad="user-123"))
    blob[20] ^= 0xFF                       # flip a bit in the ciphertext
    try:
        v.decrypt(bytes(blob), aad="user-123")
        raise AssertionError("SECURITY FAILURE: decrypted tampered ciphertext")
    except Exception:
        pass


def test_vault_aad_binds_token_to_owner():
    """
    Copying user A's token row onto user B must fail. Without AAD binding this
    is a straight privilege escalation at the database level.
    """
    v = TokenVault(key="a-test-encryption-key-value-here")
    blob = v.encrypt("user-a-token", aad="user-A")
    try:
        v.decrypt(blob, aad="user-B")
        raise AssertionError("SECURITY FAILURE: token decrypted for the wrong user")
    except Exception:
        pass


def test_vault_requires_a_key():
    import os
    saved = os.environ.pop("TOKEN_ENCRYPTION_KEY", None)
    try:
        TokenVault(key="")
        raise AssertionError("constructed a vault with no key")
    except ValueError as exc:
        assert "TOKEN_ENCRYPTION_KEY" in str(exc)
    finally:
        if saved:
            os.environ["TOKEN_ENCRYPTION_KEY"] = saved


def test_wrong_vault_key_cannot_decrypt():
    a = TokenVault(key="key-number-one-aaaaaaaaaaaaaaaaaa")
    b = TokenVault(key="key-number-two-bbbbbbbbbbbbbbbbbb")
    blob = a.encrypt("secret", aad="u1")
    try:
        b.decrypt(blob, aad="u1")
        raise AssertionError("SECURITY FAILURE: decrypted with the wrong key")
    except Exception:
        pass


# --- API keys --------------------------------------------------------------

def test_api_key_generation():
    plaintext, stored = generate_api_key()
    assert plaintext.startswith(API_KEY_PREFIX)
    assert plaintext not in stored
    assert hash_token(plaintext) == stored
    assert len({generate_api_key()[0] for _ in range(200)}) == 200


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
