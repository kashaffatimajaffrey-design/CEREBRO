"""
Live event stream (WebSocket).

The realtime path, end to end:

    detection row commits
      -> AFTER INSERT trigger calls pg_notify('cerebro_events', payload)
      -> the listener connection in core/db.py receives it (no polling)
      -> it fans the event out to every subscribed queue
      -> this handler forwards each event to its WebSocket, tenant-filtered

Two things that are easy to get wrong and are deliberately handled:

  1. **Tenant isolation still applies over the socket.** A detection carries its
     tenant_id in the notify payload; we forward an event only if it matches the
     authenticated principal's tenant. Without this, every browser would see
     every tenant's detections — RLS on the tables would be undone at the edge.

  2. **WebSockets cannot send an Authorization header from a browser.** So the
     token is read from the httpOnly session cookie (preferred) or a short-lived
     `?token=` query parameter. Either way it is verified before the socket is
     accepted; an unauthenticated client is closed, not tolerated.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from services.api.core.config import settings
from services.api.core.db import db
from services.api.core.security import TokenError, decode_access_token

log = logging.getLogger(__name__)
router = APIRouter()

# Heartbeat so idle proxies (Railway, Netlify) don't drop the socket, and so a
# half-open connection is noticed rather than lingering forever.
_PING_INTERVAL_SECONDS = 25.0


def _principal_from_ws(websocket: WebSocket, token: str | None) -> dict[str, Any] | None:
    raw = token or websocket.cookies.get("cerebro_session")
    if not raw:
        return None
    try:
        return decode_access_token(raw, settings.secret_key)
    except TokenError as exc:
        log.info("stream auth rejected: %s", exc)
        return None


@router.websocket("/stream")
async def stream(websocket: WebSocket, token: str | None = Query(None)) -> None:
    principal = _principal_from_ws(websocket, token)
    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    tenant_id = principal["tid"]
    await websocket.accept()
    log.info("stream opened for tenant %s (%d subscribers)", tenant_id, db.subscriber_count + 1)

    try:
        async with db.subscribe() as queue:
            await websocket.send_json({"event": "connected", "tenant_id": tenant_id})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_PING_INTERVAL_SECONDS)
                except asyncio.TimeoutError:
                    # Nothing to send; keep the connection warm.
                    await websocket.send_json({"event": "ping"})
                    continue

                # Tenant filter — the whole reason this isn't a broadcast.
                if str(event.get("tenant_id")) == str(tenant_id):
                    await websocket.send_json(event)
    except WebSocketDisconnect:
        log.info("stream closed for tenant %s", tenant_id)
    except Exception as exc:  # noqa: BLE001 - never let one socket crash the app
        log.warning("stream error for tenant %s: %s", tenant_id, exc)
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except Exception:  # noqa: BLE001
            pass
