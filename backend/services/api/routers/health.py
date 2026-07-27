"""Health and readiness endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready(request: Request) -> dict[str, Any]:
    """
    Readiness reports which capabilities are actually available.

    Note that `llm: false` does NOT make the service unready. Detection does not
    depend on a language model; only prose generation does. Conflating the two
    is how a product ends up unable to work without a vendor.
    """
    llm_ok = False
    try:
        llm_ok = await request.app.state.llm.health()
    except Exception:  # noqa: BLE001
        llm_ok = False

    db_ok = False
    try:
        from services.api.core.db import db
        db_ok = await db.ping()
    except Exception:  # noqa: BLE001
        db_ok = False

    return {
        "status": "ready",
        "uptime_seconds": round(time.time() - request.app.state.started_at, 1),
        "capabilities": {
            "email_forensics": True,       # deterministic, always available
            "database": db_ok,             # metrics/flows/stream depend on this
            "llm_explanations": llm_ok,    # optional
            "models_loaded": sorted(getattr(request.app.state, "models", {})),
        },
    }
