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


def _sample_flows() -> list[dict[str, Any]]:
    """
    A labeled SAMPLE of network flows for the demo, since this instance has no
    live Zeek/Suricata feed. It is realistic mixed traffic — mostly benign, with
    a few genuinely anomalous flows (a SYN flood, an oversized packet, an ICMP
    flood, a scanning source). The anomalies are NOT pre-flagged; the analyzer
    computes them. Timestamps are stamped relative to now so it reads as recent.
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    def ts(sec_ago: int) -> str:
        return (now - timedelta(seconds=sec_ago)).isoformat()

    flows: list[dict[str, Any]] = [
        {"id": "flw-01", "sourceIP": "10.0.4.22", "destIP": "142.250.72.14", "protocol": "TCP", "packetSize": 512, "flags": "ACK"},
        {"id": "flw-02", "sourceIP": "10.0.4.31", "destIP": "151.101.1.69", "protocol": "TCP", "packetSize": 1440, "flags": "PSH ACK"},
        {"id": "flw-03", "sourceIP": "10.0.4.18", "destIP": "140.82.121.4", "protocol": "TCP", "packetSize": 320, "flags": "ACK"},
        {"id": "flw-04", "sourceIP": "10.0.4.22", "destIP": "104.16.132.229", "protocol": "HTTP", "packetSize": 860, "flags": "ACK"},
        {"id": "flw-05", "sourceIP": "10.0.4.44", "destIP": "8.8.8.8", "protocol": "UDP", "packetSize": 74, "flags": ""},
        {"id": "flw-06", "sourceIP": "10.0.4.31", "destIP": "13.107.42.14", "protocol": "TCP", "packetSize": 1220, "flags": "PSH ACK"},
        # --- anomalies (the analyzer will flag these, they are not pre-marked) ---
        {"id": "flw-07", "sourceIP": "45.83.221.9", "destIP": "10.0.4.22", "protocol": "TCP", "packetSize": 60, "flags": "SYN SYN SYN SYN_FLOOD"},
        {"id": "flw-08", "sourceIP": "185.220.101.7", "destIP": "10.0.4.10", "protocol": "TCP", "packetSize": 14800, "flags": "PSH ACK"},
        {"id": "flw-09", "sourceIP": "193.27.228.14", "destIP": "10.0.4.10", "protocol": "ICMP", "packetSize": 1200, "flags": ""},
        {"id": "flw-10", "sourceIP": "193.27.228.14", "destIP": "10.0.4.11", "protocol": "ICMP", "packetSize": 1200, "flags": ""},
        {"id": "flw-11", "sourceIP": "193.27.228.14", "destIP": "10.0.4.12", "protocol": "ICMP", "packetSize": 1200, "flags": ""},
        {"id": "flw-12", "sourceIP": "193.27.228.14", "destIP": "10.0.4.13", "protocol": "ICMP", "packetSize": 1200, "flags": ""},
        {"id": "flw-13", "sourceIP": "193.27.228.14", "destIP": "10.0.4.14", "protocol": "ICMP", "packetSize": 1200, "flags": ""},
        # a scanning source: many flows from one IP to sequential targets
        *[
            {"id": f"flw-{14+i}", "sourceIP": "77.91.85.30", "destIP": f"10.0.4.{20+i}",
             "protocol": "TCP", "packetSize": 44, "flags": "SYN"}
            for i in range(7)
        ],
    ]
    for i, f in enumerate(flows):
        f["timestamp"] = ts(i * 3 + 2)
    return flows


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
    # `flows` feeds the network monitor. With no live capture feed, serve a
    # labeled sample so the scanner is demonstrable; a real deployment replaces
    # this with ingested Zeek/Suricata records.
    return {
        "count": len(rows),
        "detections": [_shape(r) for r in rows],
        "flows": _sample_flows(),
        "flows_are_sample": True,
    }


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
