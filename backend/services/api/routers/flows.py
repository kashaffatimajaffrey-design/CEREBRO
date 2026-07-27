"""
Detection feed and open incidents.

This replaces v1's `generateMockLogs()` — the function that fabricated network
logs and planted `logs[3].flags = 'SYN_FLOOD'` so the demo always had something
to show. Here `/v1/flows/recent` returns real rows from the detections table,
scoped to the caller's tenant, or an empty list if nothing has been detected.
An empty feed is the honest answer, not a reason to invent data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from services.api.core.db import db
from services.api.core.deps import Principal, current_principal
from services.api.core.queries import get_query

router = APIRouter(prefix="/flows", tags=["flows"])


@router.get("/recent", summary="Most recent detections across all modules")
async def recent(
    principal: Principal = Depends(current_principal),
    limit: int = Query(50, ge=1, le=500),
    module: str | None = Query(None, pattern="^(email|news|network)$"),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id,
        get_query("recent_detections"),
        principal.tenant_id, limit, module,
    )
    return {"count": len(rows), "detections": [_shape(r) for r in rows]}


@router.get("/incidents", summary="Open and investigating incidents, by severity")
async def incidents(
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id, get_query("open_incidents"), principal.tenant_id
    )
    return {"count": len(rows), "incidents": [_shape(r) for r in rows]}


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    from decimal import Decimal

    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = str(v) if k in {"id", "ref_id"} and v is not None else v
    return out
