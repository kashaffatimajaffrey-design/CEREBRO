"""
Network anomaly analysis route.

The unsupervised detector in services/ml/anomaly is real and tested, but it
requires two things this endpoint cannot conjure:

  1. **A model fitted on benign traffic.** Detection is "how poorly does this
     flow fit the learned baseline" — there is no baseline until a model is
     fitted (offline, on CIC-IDS2017 or a clean capture window) and registered.
  2. **Rich per-flow features.** The detector consumes CICFlowMeter-family
     features — packet-length and inter-arrival distributions, TCP flag counts.
     The browser's thin NetworkLog ({packetSize, flags}) does not carry them.

So this route does the honest thing v1 refused to do: when no fitted model is
loaded, it returns 501 and says exactly what is missing, rather than planting an
anomaly in the input the way `generateMockLogs()` did. When a model IS present
in app.state.models['anomaly'], it scores the submitted flows for real.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from services.api.core.deps import Principal, current_principal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analyze", tags=["network"])


class NetworkLogIn(BaseModel):
    id: str
    timestamp: str | None = None
    sourceIP: str | None = None
    destIP: str | None = None
    protocol: str | None = None
    packetSize: int | None = None
    flags: str | None = None


class NetworkAnalyzeRequest(BaseModel):
    logs: list[NetworkLogIn] = Field(default_factory=list)


@router.post("/flows", summary="Score network flows for anomalies")
async def analyze_flows(
    req: NetworkAnalyzeRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    detector = getattr(request.app.state, "models", {}).get("anomaly")
    if detector is None:
        # No fitted baseline — refuse rather than fabricate. The message is the
        # actionable part: it tells the operator precisely what to do next.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "No anomaly model is loaded. Network detection is unsupervised and "
                "requires a model fitted on benign traffic (see services/ml/anomaly "
                "and STATUS.md item 2). Fit on CIC-IDS2017 or a clean capture window, "
                "register the model, and load it into app.state.models['anomaly']. "
                "This endpoint will not invent a result in the meantime."
            ),
        )

    # A model IS loaded: score for real. The browser's NetworkLog is too thin
    # for full CICFlowMeter features, so this path expects richer flow records
    # (Zeek conn.log / Suricata EVE) forwarded by an ingestion worker.
    from datetime import datetime, timezone

    from services.ml.anomaly.detector import Flow

    flows: list[Flow] = [
        Flow(
            ts=datetime.now(timezone.utc),
            src_ip=lg.sourceIP or "0.0.0.0",
            dst_ip=lg.destIP or "0.0.0.0",
            protocol=(lg.protocol or "tcp").lower(),
            fwd_bytes=lg.packetSize or 0,
            flow_id=lg.id,
        )
        for lg in req.logs
    ]
    results = detector.score(flows) if flows else []

    anomalous_ids = [r.flow_id for r in results if r.is_anomaly]
    return {
        "threatLevel": "High" if anomalous_ids else "Safe",
        "anomaliesDetected": anomalous_ids,
        "analysisReport": (
            f"Scored {len(flows)} flow(s) with model {getattr(detector, 'version', 'unknown')}; "
            f"{len(anomalous_ids)} exceeded the anomaly threshold."
        ),
        "recommendedAction": (
            "Investigate the flagged flows and correlate with host logs."
            if anomalous_ids else "No action required."
        ),
        "score_source": "model",
    }
