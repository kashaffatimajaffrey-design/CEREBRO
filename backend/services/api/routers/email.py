"""
Email analysis routes.

Contrast with v1's /api/gmail-analyze, which accepted {id, subject, from, date,
snippet} and asked an LLM to perform "header forensics" on a ~100-character
snippet containing no headers.

Here the route requires the full raw message, extracts ~35 deterministic
features from it, and returns them alongside the score so the analyst can check
the reasoning. The LLM writes the summary and nothing else.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from services.api.core.db import db, emit_detection
from services.api.core.deps import Principal, current_principal
from services.ml.email.forensics import analyze_email, explain_prompt

log = logging.getLogger(__name__)
router = APIRouter()

# Enum-guarded columns in email_analyses — pass NULL rather than a value the
# CHECK constraint would reject.
_SPF_OK = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror"}
_DKIM_OK = {"pass", "fail", "none", "temperror", "permerror"}
_DMARC_OK = {"pass", "fail", "none"}
_VERDICT_OK = {"benign", "low_confidence", "suspicious", "phishing", "malicious"}


def _enum(value: str | None, allowed: set[str]) -> str | None:
    return value if value in allowed else None


async def _persist_email(principal: Principal, result: Any, score: float,
                         score_source: str, verdict: str) -> None:
    """Store the analysis so metrics populate and the data is collectable."""
    try:
        row = await db.fetchrow(
            principal.tenant_id,
            """
            INSERT INTO cerebro.email_analyses
                (tenant_id, message_id, from_display, from_addr, from_domain,
                 reply_to_addr, return_path, subject, spf, dkim, dkim_domain,
                 dmarc, dkim_aligned, features, indicators, risk_score,
                 score_source, verdict)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14::jsonb,$15::jsonb,$16,$17,$18)
            RETURNING id
            """,
            principal.tenant_id, result.message_id, result.from_display,
            result.from_addr, result.from_domain, result.reply_to_addr,
            result.return_path, result.subject,
            _enum(result.spf, _SPF_OK), _enum(result.dkim, _DKIM_OK),
            result.dkim_domain, _enum(result.dmarc, _DMARC_OK), result.dkim_aligned,
            json.dumps(result.features), json.dumps([i.as_dict() for i in result.indicators]),
            round(score, 4), score_source, _enum(verdict, _VERDICT_OK) or "benign",
        )
        await emit_detection(
            principal.tenant_id, "email", verdict, round(score, 4),
            ref_id=str(row["id"]) if row else None,
            summary=f"{verdict}: {result.from_addr or 'unknown sender'}",
        )
    except Exception as exc:  # noqa: BLE001 - persistence must never fail the response
        log.warning("email persistence skipped: %s", exc)

MAX_MESSAGE_BYTES = 10 * 1024 * 1024


class EmailAnalyzeRequest(BaseModel):
    """
    Accepts a full RFC 5322 message. Note there is no `snippet` field, by design.

    Fetch from Gmail with format='raw' to get this:
        GET /gmail/v1/users/me/messages/{id}?format=raw
    """
    raw_message: str = Field(
        ...,
        description="Full RFC 5322 message source, or base64url as returned by "
                    "the Gmail API with format=raw.",
    )
    is_base64url: bool = Field(
        default=False,
        description="Set true when passing Gmail's raw field verbatim.",
    )
    generate_explanation: bool = Field(
        default=True,
        description="Generate analyst prose. Disable for bulk scoring — the "
                    "risk score does not depend on it.",
    )

    @field_validator("raw_message")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_message must not be empty")
        if len(v) > MAX_MESSAGE_BYTES:
            raise ValueError(f"message exceeds {MAX_MESSAGE_BYTES} bytes")
        return v


class IndicatorOut(BaseModel):
    code: str
    severity: str
    weight: float
    detail: str


class EmailAnalyzeResponse(BaseModel):
    from_display: str | None
    from_addr: str | None
    from_domain: str | None
    subject: str | None
    spf: str | None
    dkim: str | None
    dmarc: str | None
    dkim_aligned: bool | None
    verdict: str
    risk_score: float = Field(..., ge=0.0, le=1.0)
    score_source: str = Field(
        ...,
        description="'heuristic' until a trained classifier is registered, then "
                    "'model'. Always stated explicitly — an unlabeled score is "
                    "an unaccountable score.",
    )
    indicators: list[IndicatorOut]
    features: dict[str, Any]
    urls: list[dict[str, Any]]
    explanation: str | None
    model_version: str | None


def _verdict_from_score(score: float) -> str:
    if score >= 0.85:
        return "phishing"
    if score >= 0.55:
        return "suspicious"
    if score >= 0.25:
        return "low_confidence"
    return "benign"


@router.post(
    "/analyze/email",
    response_model=EmailAnalyzeResponse,
    summary="Analyze a full email message for phishing indicators",
)
async def analyze(
    req: EmailAnalyzeRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> EmailAnalyzeResponse:
    raw: str | bytes = req.raw_message
    if req.is_base64url:
        try:
            padding = "=" * (-len(req.raw_message) % 4)
            raw = base64.urlsafe_b64decode(req.raw_message + padding)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"raw_message is not valid base64url: {exc}",
            ) from exc

    try:
        result = analyze_email(raw)
    except Exception as exc:  # noqa: BLE001
        log.exception("forensics failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse the message as RFC 5322 email.",
        ) from exc

    # The heuristic prior is the score until a calibrated classifier is
    # registered. Saying which one produced the number is not a detail —
    # it is the difference between a measurement and a guess.
    score = result.heuristic_risk
    score_source = "heuristic"
    model_version = None

    classifier = getattr(request.app.state, "models", {}).get("email_classifier")
    if classifier is not None:
        score = float(classifier.predict_proba(result.features))
        score_source = "model"
        model_version = classifier.version

    explanation = None
    if req.generate_explanation:
        try:
            from services.ml.providers.llm import explain
            explanation = await explain(request.app.state.llm, explain_prompt(result))
        except Exception as exc:  # noqa: BLE001
            # Explanation is cosmetic. Its failure must never fail the analysis.
            log.warning("explanation generation failed: %s", exc)

    verdict = _verdict_from_score(score)
    await _persist_email(principal, result, score, score_source, verdict)

    return EmailAnalyzeResponse(
        from_display=result.from_display,
        from_addr=result.from_addr,
        from_domain=result.from_domain,
        subject=result.subject,
        spf=result.spf,
        dkim=result.dkim,
        dmarc=result.dmarc,
        dkim_aligned=result.dkim_aligned,
        verdict=verdict,
        risk_score=round(score, 4),
        score_source=score_source,
        indicators=[IndicatorOut(**i.as_dict()) for i in result.indicators],
        features=result.features,
        urls=[u.as_dict() for u in result.urls],
        explanation=explanation,
        model_version=model_version,
    )
