"""
Authentication routes.

This is the server-side replacement for two v1 liabilities:

  - `authService.ts`, which compared passwords with `u.password === password`
    and stored them in plaintext in localStorage.
  - a Gmail token with `gmail.send` scope living in browser localStorage,
    readable by any XSS on the origin.

Here credentials are verified server-side against a scrypt hash, the access
token is a short-lived signed JWT, and it is delivered in an httpOnly cookie so
page JavaScript can never read it. The refresh token is stored only as a
SHA-256 hash — the server keeps no material that would let an attacker with read
access to the sessions table mint a login.

The Google OAuth *exchange* endpoint is scaffolded with the contract the
frontend calls, and is explicit that the authorization-code exchange itself is
not yet wired — it returns 501 rather than pretending to succeed.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field

from services.api.core.config import settings
from services.api.core.db import db
from services.api.core.deps import Principal, current_principal
from services.api.core.security import (
    create_access_token,
    generate_token,
    hash_token,
    session_expiry,
    verify_password,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "cerebro_session"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    user_id: str
    tenant_id: str
    role: str
    display_name: str | None
    # The access token is also returned in the body for non-browser API clients
    # (scripts, the parent FYP service). Browsers should rely on the cookie and
    # ignore this field.
    access_token: str
    token_type: str = "bearer"


def _set_session_cookie(response: Response, token: str) -> None:
    samesite = settings.session_cookie_samesite
    if samesite not in {"lax", "none", "strict"}:
        samesite = "lax"
    # SameSite=None is only valid on a Secure cookie. Force Secure in that case
    # even outside production, or the browser silently drops the cookie.
    secure = settings.is_production or samesite == "none"
    response.set_cookie(
        _COOKIE_NAME,
        token,
        max_age=settings.access_token_ttl_minutes * 60,
        httponly=True,
        secure=secure,
        samesite=samesite,  # type: ignore[arg-type]
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, response: Response) -> LoginResponse:
    # Uniform failure for "no such user" and "wrong password": revealing which
    # one is true hands an attacker an account-enumeration oracle.
    user = await db.fetch_unscoped(
        """
        SELECT id, tenant_id, role, display_name, password_hash, is_active
        FROM cerebro.users
        WHERE email = $1
        ORDER BY created_at
        LIMIT 1
        """,
        req.email,
    )
    row = user[0] if user else None
    if (
        row is None
        or not row["is_active"]
        or not row["password_hash"]
        or not verify_password(req.password, row["password_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid email or password",
        )

    user_id, tenant_id, role = str(row["id"]), str(row["tenant_id"]), row["role"]

    access_token = create_access_token(
        user_id=user_id, tenant_id=tenant_id, role=role,
        secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes,
    )

    # Persist a hashed refresh/session record. Only the hash is stored.
    refresh_token = generate_token()
    await db.fetch_unscoped(
        """
        INSERT INTO cerebro.sessions (user_id, token_hash, user_agent, ip, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        row["id"], hash_token(refresh_token),
        request.headers.get("user-agent"),
        request.client.host if request.client else None,
        session_expiry(),
    )
    await db.fetch_unscoped(
        "UPDATE cerebro.users SET last_seen_at = now() WHERE id = $1", row["id"]
    )

    _set_session_cookie(response, access_token)
    return LoginResponse(
        user_id=user_id, tenant_id=tenant_id, role=role,
        display_name=row["display_name"], access_token=access_token,
    )


@router.post("/logout", summary="Clear the session cookie")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/me", summary="The authenticated principal")
async def me(principal: Principal = Depends(current_principal)) -> dict[str, Any]:
    row = await db.fetch_unscoped(
        """
        SELECT id, tenant_id, email, display_name, role, last_seen_at
        FROM cerebro.users WHERE id = $1
        """,
        principal.user_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    u = row[0]
    return {
        "user_id": str(u["id"]),
        "tenant_id": str(u["tenant_id"]),
        "email": str(u["email"]),
        "display_name": u["display_name"],
        "role": u["role"],
        "last_seen_at": u["last_seen_at"].isoformat() if u["last_seen_at"] else None,
    }


class GoogleExchangeRequest(BaseModel):
    code: str = Field(..., description="OAuth 2.0 authorization code from Google")
    redirect_uri: str


@router.post("/google/exchange", summary="Exchange a Google auth code for stored, encrypted tokens")
async def google_exchange(
    req: GoogleExchangeRequest,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    """
    Server-side Gmail OAuth. The browser sends only the short-lived
    authorization code; the code-for-token swap happens here, where the client
    secret lives, and the resulting tokens are encrypted at rest and never
    returned to the browser.

    This is the fix for v1 keeping a `gmail.send`-scoped access token in
    localStorage: with this flow the token exists only server-side, AES-GCM
    encrypted and bound to the user via AAD, so a database dump does not hand an
    attacker live mailbox access and a row copied between users won't decrypt.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and "
                   "GOOGLE_CLIENT_SECRET in the environment.",
        )
    if not settings.token_encryption_key:
        # Refuse rather than store a token we cannot protect.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TOKEN_ENCRYPTION_KEY is not set; refusing to store OAuth tokens in the clear.",
        )

    import httpx

    from services.api.core.security import TokenVault

    # 1. Swap the authorization code for tokens at Google's token endpoint.
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                settings.google_token_url,
                data={
                    "code": req.code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": req.redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Google's token endpoint.",
        ) from exc

    if resp.status_code != 200:
        # Google returns {error, error_description} on a bad/expired code. Do not
        # echo the raw body — it can contain the code; log server-side instead.
        log.warning("google token exchange failed: %s", resp.status_code)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authorization code exchange was rejected by Google (expired or already used).",
        )

    tokens = resp.json()
    access_token = tokens.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google response did not contain an access token.",
        )
    refresh_token = tokens.get("refresh_token")  # only present on first consent
    expires_in = int(tokens.get("expires_in", 3600))
    scopes = (tokens.get("scope") or "").split()

    # 2. Encrypt both tokens, binding each to this user via AAD.
    vault = TokenVault(settings.token_encryption_key)
    enc_access = vault.encrypt(access_token, aad=principal.user_id)
    enc_refresh = vault.encrypt(refresh_token, aad=principal.user_id) if refresh_token else None

    # 3. Upsert. If Google withheld a refresh token (repeat consent), keep the
    #    one we already stored rather than nulling it.
    await db.fetch_unscoped(
        """
        INSERT INTO cerebro.oauth_credentials
            (user_id, provider, scopes, access_token, refresh_token, expires_at, updated_at)
        VALUES ($1, 'google', $2, $3, $4, now() + ($5 || ' seconds')::interval, now())
        ON CONFLICT (user_id, provider) DO UPDATE SET
            scopes        = EXCLUDED.scopes,
            access_token  = EXCLUDED.access_token,
            refresh_token = COALESCE(EXCLUDED.refresh_token, cerebro.oauth_credentials.refresh_token),
            expires_at    = EXCLUDED.expires_at,
            updated_at    = now()
        """,
        principal.user_id, scopes, enc_access, enc_refresh, str(expires_in),
    )

    # The browser gets confirmation and metadata only — never the token itself.
    return {
        "status": "stored",
        "provider": "google",
        "scopes": scopes,
        "expires_in": expires_in,
        "has_refresh_token": refresh_token is not None,
    }
