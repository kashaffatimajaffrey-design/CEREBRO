"""
Dashboard metrics.

Every endpoint here is a thin wrapper over a named statement in `db/queries.sql`,
run against the caller's tenant. There is no computation in Python beyond shaping
the JSON — the numbers are the database's, and they are reproducible by running
the same SQL in psql. This is the layer that replaced v1's hardcoded `threatData`
array and its `1284 + realScansCount` padding: a new tenant sees real zeros.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from services.api.core.db import db
from services.api.core.deps import Principal, current_principal
from services.api.core.queries import get_query

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", summary="Headline counts for the stat cards")
async def summary(
    principal: Principal = Depends(current_principal),
    hours: int = Query(168, ge=1, le=24 * 90),
) -> dict[str, Any]:
    row = await db.fetchrow(
        principal.tenant_id, get_query("summary"), principal.tenant_id, str(hours)
    ) or {}
    delta = await db.fetchrow(
        principal.tenant_id, get_query("summary_delta"), principal.tenant_id, str(hours)
    ) or {}
    # pct_change is what DashboardHome reads to render the trend arrow. It is
    # NULL (not 0) when there is no prior window — the UI shows no delta rather
    # than a fabricated one.
    return {
        **{k: _num(v) for k, v in row.items()},
        "window_hours": hours,
        "pct_change": delta.get("pct_change"),
        "current_count": delta.get("current_count"),
        "previous_count": delta.get("previous_count"),
    }


@router.get("/threat-volume", summary="Hourly detection volume for the main chart")
async def threat_volume(
    principal: Principal = Depends(current_principal),
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id, get_query("threat_volume"), principal.tenant_id, str(days)
    )
    # generate_series in the query guarantees a continuous x-axis: quiet hours
    # are explicit zeros, so the chart cannot misrepresent a lull by omission.
    return {
        "days": days,
        "buckets": [
            {
                "bucket": _iso(r["bucket"]),
                "total": r["total"],
                "email": r["email"],
                "news": r["news"],
                "network": r["network"],
                "avg_risk": _num(r["avg_risk"]),
            }
            for r in rows
        ],
    }


@router.get("/detection-rates", summary="Per-module severity breakdown")
async def detection_rates(
    principal: Principal = Depends(current_principal),
    days: int = Query(7, ge=1, le=90),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id, get_query("detection_rates"), principal.tenant_id, str(days)
    )
    return {"days": days, "modules": [_shape(r) for r in rows]}


@router.get("/top-domains", summary="Domains most frequently attacking this tenant")
async def top_domains(
    principal: Principal = Depends(current_principal),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=100),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id,
        get_query("top_threat_domains"),
        principal.tenant_id, str(days), limit,
    )
    return {"days": days, "domains": [_shape(r) for r in rows]}


@router.get("/auth-breakdown", summary="SPF/DKIM/DMARC pass-fail telemetry")
async def auth_breakdown(
    principal: Principal = Depends(current_principal),
    days: int = Query(30, ge=1, le=365),
) -> dict[str, Any]:
    row = await db.fetchrow(
        principal.tenant_id,
        get_query("auth_failure_breakdown"),
        principal.tenant_id, str(days),
    ) or {}
    return {"days": days, **{k: _num(v) for k, v in row.items()}}


@router.get("/models", summary="Active model versions and their published metrics")
async def active_models(
    _principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    # The model registry is not tenant-scoped — it is shared reference data.
    rows = await db.fetch_unscoped(get_query("model_versions_active"))
    return {"models": [_shape(r) for r in rows]}


# --- shaping helpers -------------------------------------------------------

def _num(value: Any) -> Any:
    """Postgres numeric/Decimal -> float for clean JSON; pass ints/None through."""
    from decimal import Decimal

    if isinstance(value, Decimal):
        return float(value)
    return value


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _iso(_num(v)) for k, v in row.items()}
