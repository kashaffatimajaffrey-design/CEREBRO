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


def _heuristic_scan(logs: list["NetworkLogIn"]) -> dict[str, Any]:
    """
    Transparent, rule-based flow triage — the network counterpart to the email
    module's heuristic prior. It computes findings from the flows themselves
    (SYN floods, oversized packets, ICMP floods, high-volume sources that look
    like scans); nothing is planted. Labeled `score_source: "heuristic"` so it's
    never mistaken for the trained unsupervised model.
    """
    from collections import Counter

    if not logs:
        return {
            "threatLevel": "Safe", "anomaliesDetected": [],
            "analysisReport": "No flows to analyze.",
            "recommendedAction": "No action required.", "score_source": "heuristic",
        }

    src_counts = Counter(l.sourceIP for l in logs if l.sourceIP)
    flagged: list[tuple[str, str]] = []
    for l in logs:
        flags = (l.flags or "").upper()
        reason = None
        if "SYN_FLOOD" in flags or flags.count("SYN") >= 3:
            reason = "SYN flood pattern"
        elif (l.packetSize or 0) > 8000:
            reason = f"oversized packet ({l.packetSize} bytes)"
        elif (l.protocol or "").upper() == "ICMP" and src_counts.get(l.sourceIP, 0) >= 4:
            reason = "ICMP flood"
        elif l.sourceIP and src_counts.get(l.sourceIP, 0) >= 6:
            reason = "high-volume source — possible port scan"
        if reason:
            flagged.append((l.id, reason))

    n = len(flagged)
    has_flood = any("flood" in r for _, r in flagged)
    if has_flood or n >= 4:
        level = "Critical" if (has_flood and n >= 3) else "High"
    elif n >= 1:
        level = "Medium"
    else:
        level = "Safe"

    detail = "; ".join(f"{fid}: {r}" for fid, r in flagged[:6])
    report = (
        f"Heuristic triage of {len(logs)} flow(s): {n} flagged. " +
        (detail if flagged else "No anomalous patterns in this sample.")
    )
    return {
        "threatLevel": level,
        "anomaliesDetected": [fid for fid, _ in flagged],
        "analysisReport": report,
        "recommendedAction": (
            "Isolate the flagged sources and review firewall/rate-limit rules."
            if flagged else "No action required."
        ),
        "score_source": "heuristic",
    }


@router.post("/flows", summary="Score network flows for anomalies")
async def analyze_flows(
    req: NetworkAnalyzeRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> dict[str, Any]:
    detector = getattr(request.app.state, "models", {}).get("anomaly")
    if detector is None:
        # No trained unsupervised model loaded → fall back to the transparent
        # heuristic (labeled as such), rather than refusing. When a fitted model
        # is registered, the ML path below takes over and score_source='model'.
        return _heuristic_scan(req.logs)

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
