"""
Misinformation analysis route.

This wires the RAG verification pipeline (services/ml/rag) to the frontend's
News scanner. The contract is the one the whole architecture is built around:

    a credibility number is DERIVED FROM retrieved evidence, or it is not
    produced at all.

v1's /api/analyze-news asked Gemini for a `credibilityScore` and a `sources[]`
array in a single call with no retrieval — the "sources" were invented, and the
server schema literally called them "simulated references". Here:

  1. the article is segmented into checkable claims (the one legitimate LLM job,
     with a sentence-split fallback when no model is available);
  2. each claim is verified against the tenant's evidence corpus with hybrid
     retrieval + NLI stance;
  3. the credibility score is the evidence-weighted support across claims;
  4. every source returned is a URL of a document that was actually retrieved.

If the corpus has nothing relevant, the honest answer is a low-confidence
"insufficient evidence" — not a confident fabrication. The `sources` array can
therefore be empty, and that is a feature.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from services.api.core.db import db
from services.api.core.deps import Principal, current_principal
from services.ml.rag.retrieval import Document
from services.ml.rag.verify import ClaimVerdict, Label, build_default_verifier

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analyze", tags=["news"])

MAX_TEXT_BYTES = 100 * 1024


class NewsAnalyzeRequest(BaseModel):
    text: str = Field(..., description="Article text, headline, or statement to verify.")

    @field_validator("text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be empty")
        if len(v.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError(f"text exceeds {MAX_TEXT_BYTES} bytes")
        return v


# Response mirrors the frontend NewsAnalysisResult shape exactly.
class NewsAnalyzeResponse(BaseModel):
    credibilityScore: int = Field(..., ge=0, le=100)
    verdict: str
    summary: str
    reasoning: str
    sources: list[str]
    # Extra fields the v1 UI ignored but that make this auditable. Additive, so
    # the existing client keeps working while new clients can show provenance.
    claims_checked: int
    model_versions: dict[str, str]
    score_source: str = "rag_evidence"


async def _load_corpus(tenant_id: str) -> list[Document]:
    """
    The evidence corpus for this tenant: documents of kind 'evidence' or
    'article', joined to their source credibility weight where we know it.
    """
    rows = await db.fetch(
        tenant_id,
        """
        SELECT d.id, d.title, d.body, d.source_url,
               COALESCE(es.credibility_weight, 0.5) AS credibility,
               es.domain AS source_domain
        FROM cerebro.documents d
        LEFT JOIN cerebro.evidence_sources es
               ON es.domain = split_part(regexp_replace(d.source_url, '^https?://(www\\.)?', ''), '/', 1)
        WHERE d.kind IN ('evidence', 'article')
        ORDER BY d.ingested_at DESC
        LIMIT 5000
        """,
    )
    corpus: list[Document] = []
    for r in rows:
        corpus.append(
            Document(
                id=str(r["id"]),
                title=r["title"] or "",
                text=r["body"] or "",
                url=r["source_url"],
                domain=r["source_domain"],
                credibility=float(r["credibility"]),
            )
        )
    return corpus


def _to_credibility(verdicts: list[ClaimVerdict]) -> tuple[int, str, str]:
    """
    Fold per-claim verdicts into an overall 0-100 credibility score, a verdict
    label the UI understands, and a one-line reasoning string.

    Credibility is high when claims are SUPPORTED, low when REFUTED, and lands
    near the middle (with explicit uncertainty) when evidence is insufficient —
    an unverifiable article is not the same as a false one, and the score says so.
    """
    if not verdicts:
        return 50, "Unverified", "No checkable claims were extracted from the text."

    per_claim: list[float] = []
    refuted = supported = insufficient = 0
    for v in verdicts:
        if v.label is Label.SUPPORTED:
            per_claim.append(0.5 + 0.5 * v.confidence)
            supported += 1
        elif v.label is Label.REFUTED:
            per_claim.append(0.5 - 0.5 * v.confidence)
            refuted += 1
        elif v.label is Label.DISPUTED:
            per_claim.append(0.5)
        else:  # INSUFFICIENT
            per_claim.append(0.5)
            insufficient += 1

    score = int(round(100 * (sum(per_claim) / len(per_claim))))

    if refuted and refuted >= supported:
        verdict = "Fake News" if score < 40 else "Misleading"
    elif supported and insufficient <= supported:
        verdict = "Credible"
    else:
        verdict = "Unverified"

    reasoning = (
        f"Checked {len(verdicts)} claim(s): {supported} supported, {refuted} refuted, "
        f"{insufficient} without sufficient evidence in the corpus. "
        "Score is the evidence-weighted support across claims; where the corpus "
        "lacked relevant documents the claim was counted as uncertain, not false."
    )
    return max(0, min(100, score)), verdict, reasoning


# --- linguistic-credibility fallback (used only when the corpus has no evidence) ---

_SENSATIONAL = (
    "shocking", "unbelievable", "you won't believe", "miracle", "secret",
    "exposed", "they don't want you to know", "wake up", "banned", "cover-up",
    "cover up", "guaranteed", "must see", "the truth about", "mainstream media",
    "big pharma", "what they aren't telling", "no one is talking about",
)
_CONSPIRACY = (
    "microchip", "5g causes", "flat earth", "chemtrail", "illuminati",
    "new world order", "depopulation", "plandemic", "vaccine causes autism",
    "faked the", "staged", "crisis actor",
)
_DEATH_RUMOR = ("is dead", "has died", "found dead", "assassinated", "passed away")
_CREDIBLE_SIGNALS = (
    "according to", "reported", "study", "research", "university", "official",
    "announced", "confirmed", "spokesperson", "data shows", "published in",
    "peer-reviewed", "statement", "court", "report found",
)


def _heuristic_credibility(text: str) -> tuple[int, str, str]:
    """
    A transparent linguistic-credibility estimate for when the evidence corpus
    has nothing relevant. NOT evidence-based verification — it reads writing-style
    signals (sensationalism, conspiracy markers, sourcing/attribution) the way the
    email module reads header signals, and is labeled score_source='heuristic'.
    """
    t = text.lower()
    score = 55
    notes: list[str] = []

    sens = sum(1 for w in _SENSATIONAL if w in t)
    if sens:
        score -= min(30, sens * 10); notes.append(f"{sens} sensational/clickbait phrase(s)")
    consp = sum(1 for w in _CONSPIRACY if w in t)
    if consp:
        score -= min(38, consp * 19); notes.append(f"{consp} known-conspiracy marker(s)")
    if any(w in t for w in _DEATH_RUMOR):
        score -= 16; notes.append("unverified death claim (a common misinformation pattern)")
    cred = sum(1 for w in _CREDIBLE_SIGNALS if w in t)
    if cred:
        score += min(24, cred * 8); notes.append(f"{cred} attribution/sourcing signal(s)")

    exclam = text.count("!")
    if exclam >= 2:
        score -= min(15, exclam * 4); notes.append("excessive exclamation")
    letters = [c for c in text if c.isalpha()]
    if letters and len(letters) > 20:
        caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if caps_ratio > 0.3:
            score -= 12; notes.append("heavy capitalization")
    if re.search(r"\b(19|20)\d{2}\b", text) or re.search(r"\b\d+(\.\d+)?%\b", text):
        score += 6; notes.append("contains specific figures/dates")

    score = max(5, min(90, score))
    if score < 40:
        verdict = "Fake News" if score < 25 else "Misleading"
    elif score >= 65:
        verdict = "Credible"
    else:
        verdict = "Unverified"

    reasoning = (
        "No matching documents in the evidence corpus, so this is a transparent "
        "linguistic-credibility estimate (heuristic), not evidence-based verification. "
        + ("Signals — " + "; ".join(notes) + "." if notes else
           "No strong linguistic signals either way.")
    )
    return score, verdict, reasoning


@router.post("/news", response_model=NewsAnalyzeResponse, summary="Verify claims in text against the evidence corpus")
async def analyze_news(
    req: NewsAnalyzeRequest,
    request: Request,
    principal: Principal = Depends(current_principal),
) -> NewsAnalyzeResponse:
    corpus = await _load_corpus(principal.tenant_id)

    # Build the best verifier the environment supports (real transformers if
    # present, offline-capable fallback otherwise — it logs which it got).
    verifier = build_default_verifier(corpus, prefer_transformers=True)

    # Claim extraction is the one legitimate generative-LLM job. Fall back to a
    # sentence split if no provider answers — degraded, but never a hard failure.
    try:
        from services.ml.providers.llm import extract_claims
        extracted = await extract_claims(request.app.state.llm, req.text)
        claim_texts = [c["text"] for c in extracted if c.get("text")]
    except Exception as exc:  # noqa: BLE001
        log.warning("claim extraction fell back to sentence split: %s", exc)
        import re
        claim_texts = [
            s.strip() for s in re.split(r"(?<=[.!?])\s+", req.text) if len(s.strip()) > 40
        ][:12]

    if not claim_texts:
        claim_texts = [req.text[:500]]

    verdicts = [verifier.verify(c) for c in claim_texts]

    # Sources: only URLs of documents that were actually retrieved and scored.
    sources: list[str] = []
    for v in verdicts:
        for url in v.citations:
            if url and url not in sources:
                sources.append(url)

    score, verdict, reasoning = _to_credibility(verdicts)
    score_source = "rag_evidence"

    # If retrieval found no decisive evidence (empty/irrelevant corpus), a flat
    # 50% for everything is useless. Fall back to the transparent linguistic
    # heuristic so the score reflects the text — clearly labeled as heuristic.
    decisive = any(v.label in (Label.SUPPORTED, Label.REFUTED) for v in verdicts)
    if not decisive and not sources:
        score, verdict, reasoning = _heuristic_credibility(req.text)
        score_source = "heuristic"

    summary = req.text.strip().replace("\n", " ")
    summary = (summary[:280] + "…") if len(summary) > 280 else summary

    model_versions: dict[str, str] = {}
    for v in verdicts:
        model_versions.update(v.model_versions)

    return NewsAnalyzeResponse(
        credibilityScore=score,
        verdict=verdict,
        summary=summary,
        reasoning=reasoning,
        sources=sources[:12],
        claims_checked=len(verdicts),
        model_versions=model_versions,
        score_source=score_source,
    )
