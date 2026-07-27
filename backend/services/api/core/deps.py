"""
Request dependencies — principally, "who is calling and which tenant are they".

Every data route depends on `current_principal`. It resolves the caller from a
signed JWT (or the httpOnly session cookie carrying one) and returns the tenant
id that RLS will scope every subsequent query to. No route reads a tenant id
from a query string or request body — that would let any caller ask for another
tenant's data. The only source of truth is the verified token.

`decode_access_token` (in core/security.py) already rejects `alg=none`, bad
signatures, expiry, and missing claims; this layer turns a valid token into a
typed principal and turns everything else into a clean 401.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.api.core.config import settings
from services.api.core.security import TokenError, decode_access_token

# auto_error=False so we can also accept the session cookie, not only the header.
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    role: str

    def require_role(self, *allowed: str) -> None:
        if self.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{self.role}' is not permitted to perform this action",
            )


def _token_from_request(
    request: Request, creds: HTTPAuthorizationCredentials | None
) -> str | None:
    if creds is not None and creds.scheme.lower() == "bearer":
        return creds.credentials
    # Fall back to the httpOnly cookie set at login — this is the path the
    # browser SPA uses, so the token never touches JavaScript.
    return request.cookies.get("cerebro_session")


async def current_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    token = _token_from_request(request, creds)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(token, settings.secret_key)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Principal(
        user_id=payload["sub"],
        tenant_id=payload["tid"],
        role=payload.get("role", "viewer"),
    )
