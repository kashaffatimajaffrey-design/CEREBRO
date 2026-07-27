"""
Forecast serving.

This route only *reads* the `forecasts` table (via the `forecast_series` named
query). Forecasts are produced by an offline TFT job — see
`services/ml/forecast/tft.py` — and written there; the interactive request path
never loads torch.

The honest cold-start contract: when no forecast exists for a series yet (the
usual case until weeks of history accumulate), this returns
`status: "insufficient_history"` with an empty series, not a fabricated curve.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from services.api.core.db import db
from services.api.core.deps import Principal, current_principal
from services.api.core.queries import get_query

router = APIRouter(prefix="/forecast", tags=["forecast"])


@router.get("/{series}", summary="Latest quantile forecast for a series")
async def forecast(
    series: str,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    rows = await db.fetch(
        principal.tenant_id, get_query("forecast_series"), principal.tenant_id, series
    )
    if not rows:
        return {
            "series": series,
            "status": "insufficient_history",
            "message": "No forecast has been produced for this series yet. The TFT "
                       "model trains once enough detection history has accumulated.",
            "horizon": [],
        }

    def _num(v: Any) -> Any:
        from decimal import Decimal
        return float(v) if isinstance(v, Decimal) else v

    return {
        "series": series,
        "status": "ok",
        "issued_at": rows[0]["issued_at"].isoformat() if rows[0].get("issued_at") else None,
        "horizon": [
            {
                "horizon_ts": r["horizon_ts"].isoformat() if r.get("horizon_ts") else None,
                "p10": _num(r["p10"]),
                "p50": _num(r["p50"]),
                "p90": _num(r["p90"]),
            }
            for r in rows
        ],
    }
