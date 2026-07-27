"""
Claim verification: retrieve evidence, judge stance, aggregate to a verdict.

The contract this module enforces, and the reason it exists:

    A verdict may only cite documents that were actually retrieved.

v1 produced a `credibilityScore` and a `sources[]` array from a single Gemini
call with no retrieval step. Here the verdict is *derived from* the evidence —
if retrieval returns nothing, the answer is `insufficient_evidence`, not a
confident guess. That failure mode is the point: a fact-checker that never says
"I don't know" is not a fact-checker.

Stance detection uses an NLI model (RoBERTa fine-tuned on MNLI, optionally
further fine-tuned on FEVER). For each (claim, evidence) pair it answers a
question the model is actually trained for — does this passage entail or
contradict this statement — rather than the open-ended "is this fake news",
which no model is calibrated for.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, Sequence

from services.ml.rag.retrieval import Document, HybridRetriever, ScoredDocument

log = logging.getLogger(__name__)


class Stance(str, Enum):
    ENTAIL = "entail"
    CONTRADICT = "contradict"
    NEUTRAL = "neutral"


class Label(str, Enum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    DISPUTED = "disputed"
    INSUFFICIENT = "insufficient_evidence"


@dataclass
class EvidenceItem:
    document_id: str
    url: str | None
    title: str
    snippet: str
    domain: str | None
    credibility: float
    stance: Stance
    nli_score: float
    retrieval_score: float
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "domain": self.domain,
            "credibility": round(self.credibility, 3),
            "stance": self.stance.value,
            "nli_score": round(self.nli_score, 4),
            "retrieval_score": round(self.retrieval_score, 6),
            "rerank_score": round(self.rerank_score, 4) if self.rerank_score else None,
        }


@dataclass
class ClaimVerdict:
    claim: str
    label: Label
    confidence: float
    evidence: list[EvidenceItem] = field(default_factory=list)
    support_weight: float = 0.0
    refute_weight: float = 0.0
    explanation: str | None = None
    model_versions: dict[str, str] = field(default_factory=dict)

    @property
    def citations(self) -> list[str]:
        """Only URLs of documents that were actually retrieved and scored."""
        return [e.url for e in self.evidence if e.url]

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "label": self.label.value,
            "confidence": round(self.confidence, 4),
            "support_weight": round(self.support_weight, 4),
            "refute_weight": round(self.refute_weight, 4),
            "evidence_count": len(self.evidence),
            "evidence": [e.as_dict() for e in self.evidence],
            "citations": self.citations,
            "explanation": self.explanation,
            "model_versions": self.model_versions,
        }


# ---------------------------------------------------------------------------
# Stance detection
# ---------------------------------------------------------------------------

class StanceModel(Protocol):
    name: str
    def predict(self, claim: str, evidence: str) -> tuple[Stance, float]: ...


class NLIStanceModel:
    """
    Production stance detector: `roberta-large-mnli` (or a FEVER-tuned variant).

    Direction matters and is easy to get backwards: the evidence is the
    *premise* and the claim is the *hypothesis*. Asking "does this passage imply
    this claim" is the correct framing; reversing it changes what entailment
    means and quietly degrades accuracy.
    """

    def __init__(self, model_name: str = "roberta-large-mnli") -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        import torch

        self.name = model_name
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
        self._model.eval()

        # Label order differs between checkpoints; read it from config rather
        # than hardcoding indices.
        self._id2label = {
            int(k): v.lower() for k, v in self._model.config.id2label.items()
        }

    def predict(self, claim: str, evidence: str) -> tuple[Stance, float]:
        inputs = self._tokenizer(
            evidence, claim, return_tensors="pt",
            truncation=True, max_length=512, padding=True,
        )
        with self._torch.no_grad():
            logits = self._model(**inputs).logits
        probs = self._torch.softmax(logits, dim=-1)[0]

        best_idx = int(probs.argmax())
        label = self._id2label.get(best_idx, "neutral")
        score = float(probs[best_idx])

        if "entail" in label:
            return Stance.ENTAIL, score
        if "contradict" in label:
            return Stance.CONTRADICT, score
        return Stance.NEUTRAL, score


class LexicalStanceModel:
    """
    Dependency-free fallback for offline testing and cold start.

    Overlap plus negation-mismatch heuristics. Genuinely weak — it is here so
    the pipeline is testable and degrades to *worse stance detection* rather
    than crashing when transformers is unavailable. Never report metrics from
    this model as if they were the system's accuracy.
    """

    name = "lexical-fallback-v1"

    _NEGATIONS = frozenset({
        "not", "no", "never", "none", "neither", "nor", "cannot", "cant",
        "didnt", "doesnt", "isnt", "wasnt", "werent", "wont", "denied",
        "denies", "false", "hoax", "debunked", "refuted", "incorrect",
        "untrue", "misleading", "fabricated",
    })

    def predict(self, claim: str, evidence: str) -> tuple[Stance, float]:
        from services.ml.rag.retrieval import tokenize

        claim_tokens = set(tokenize(claim))
        evidence_tokens = tokenize(evidence)
        evidence_set = set(evidence_tokens)
        if not claim_tokens or not evidence_set:
            return Stance.NEUTRAL, 0.5

        overlap = len(claim_tokens & evidence_set) / len(claim_tokens)
        if overlap < 0.25:
            return Stance.NEUTRAL, 0.5 + 0.3 * (1 - overlap)

        # A negation present on one side but not the other flips the stance.
        claim_negated = bool(claim_tokens & self._NEGATIONS)
        evidence_negated = bool(evidence_set & self._NEGATIONS)
        confidence = min(0.5 + overlap * 0.45, 0.95)

        if claim_negated != evidence_negated:
            return Stance.CONTRADICT, confidence
        return Stance.ENTAIL, confidence


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

class CrossEncoderReranker:
    """
    `ms-marco-MiniLM-L-6-v2` cross-encoder.

    Retrieval optimizes recall over thousands of documents; a cross-encoder
    reads the query and document *together* and optimizes precision over the
    top ~50. Running it on everything would be far too slow — running it on the
    candidate pool is where most of the quality gain in a RAG system lives.
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        from sentence_transformers import CrossEncoder
        self.name = model_name
        self._model = CrossEncoder(model_name)

    def rerank(self, query: str, hits: Sequence[ScoredDocument],
               top_k: int = 8) -> list[ScoredDocument]:
        if not hits:
            return []
        pairs = [(query, h.document.searchable[:2000]) for h in hits]
        scores = self._model.predict(pairs)
        for hit, score in zip(hits, scores):
            hit.rerank_score = float(score)
        return sorted(hits, key=lambda h: -(h.rerank_score or 0))[:top_k]


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

class ClaimVerifier:
    """
    Retrieve → (rerank) → stance → aggregate.

    Aggregation weights each piece of evidence by both its retrieval rank and
    its source credibility, so a contradicting Reuters article outweighs three
    supporting blog posts. Those weights are stored on the verdict, so the
    arithmetic is auditable rather than a black box.
    """

    def __init__(
        self,
        retriever: HybridRetriever,
        stance_model: StanceModel | None = None,
        reranker: Any | None = None,
        *,
        candidate_k: int = 20,
        evidence_k: int = 6,
        min_confidence: float = 0.55,
        min_evidence: int = 1,
    ) -> None:
        self.retriever = retriever
        self.stance_model = stance_model or LexicalStanceModel()
        self.reranker = reranker
        self.candidate_k = candidate_k
        self.evidence_k = evidence_k
        self.min_confidence = min_confidence
        self.min_evidence = min_evidence

    def verify(self, claim: str) -> ClaimVerdict:
        if not claim or not claim.strip():
            return ClaimVerdict(claim=claim, label=Label.INSUFFICIENT, confidence=0.0)

        hits = self.retriever.search(claim, top_k=self.candidate_k)

        # No evidence means no verdict. This branch is the whole point of the
        # module — v1 had no equivalent and always produced a confident answer.
        if not hits:
            return ClaimVerdict(
                claim=claim, label=Label.INSUFFICIENT, confidence=0.0,
                explanation="No documents in the evidence corpus matched this claim.",
                model_versions=self._versions(),
            )

        if self.reranker is not None:
            hits = self.reranker.rerank(claim, hits, top_k=self.evidence_k)
        else:
            hits = hits[:self.evidence_k]

        evidence: list[EvidenceItem] = []
        support = refute = 0.0

        for rank, hit in enumerate(hits, start=1):
            stance, nli_score = self.stance_model.predict(claim, hit.document.searchable)
            # Rank decay: the 6th result should not count as much as the 1st.
            rank_weight = 1.0 / math.log2(rank + 1.5)
            weight = nli_score * hit.document.credibility * rank_weight

            if stance is Stance.ENTAIL:
                support += weight
            elif stance is Stance.CONTRADICT:
                refute += weight

            evidence.append(EvidenceItem(
                document_id=hit.document.id,
                url=hit.document.url,
                title=hit.document.title,
                snippet=hit.document.text[:300],
                domain=hit.document.domain,
                credibility=hit.document.credibility,
                stance=stance,
                nli_score=nli_score,
                retrieval_score=hit.score,
                rerank_score=hit.rerank_score,
            ))

        label, confidence = self._aggregate(support, refute, evidence)

        return ClaimVerdict(
            claim=claim, label=label, confidence=confidence,
            evidence=evidence, support_weight=support, refute_weight=refute,
            model_versions=self._versions(),
        )

    def _aggregate(
        self, support: float, refute: float, evidence: Sequence[EvidenceItem],
    ) -> tuple[Label, float]:
        decisive = [e for e in evidence if e.stance is not Stance.NEUTRAL]
        if len(decisive) < self.min_evidence:
            return Label.INSUFFICIENT, 0.0

        total = support + refute
        if total <= 0:
            return Label.INSUFFICIENT, 0.0

        margin = abs(support - refute) / total

        # Genuine disagreement between credible sources is its own answer, and
        # a more honest one than picking the larger pile.
        if margin < 0.2 and len(decisive) >= 2:
            return Label.DISPUTED, round(0.5 + margin, 4)

        confidence = round(min(0.99, margin * (1 - math.exp(-total))), 4)
        if confidence < self.min_confidence:
            return Label.INSUFFICIENT, confidence

        return (Label.SUPPORTED if support > refute else Label.REFUTED), confidence

    def _versions(self) -> dict[str, str]:
        v = {
            "stance": getattr(self.stance_model, "name", "unknown"),
            "embedder": type(self.retriever.embedder).__name__,
        }
        if self.reranker is not None:
            v["reranker"] = getattr(self.reranker, "name", "unknown")
        return v


def build_default_verifier(
    documents: Sequence[Document], *, prefer_transformers: bool = True,
) -> ClaimVerifier:
    """
    Construct the best pipeline the environment supports.

    Tries the real models first and falls back to offline-capable versions,
    logging loudly which one it got — so nobody mistakes fallback quality for
    production quality.
    """
    from services.ml.rag.retrieval import HashingEmbedder, SentenceTransformerEmbedder

    embedder: Any
    stance: Any
    reranker: Any = None

    if prefer_transformers:
        try:
            embedder = SentenceTransformerEmbedder()
            stance = NLIStanceModel()
            try:
                reranker = CrossEncoderReranker()
            except Exception as exc:  # noqa: BLE001
                log.warning("reranker unavailable: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "TRANSFORMERS UNAVAILABLE (%s) — falling back to hashing embedder "
                "and lexical stance. Retrieval quality will be materially worse; "
                "do not report metrics from this configuration.", exc,
            )
            embedder, stance = HashingEmbedder(), LexicalStanceModel()
    else:
        embedder, stance = HashingEmbedder(), LexicalStanceModel()

    retriever = HybridRetriever(embedder=embedder).index(documents)
    return ClaimVerifier(retriever=retriever, stance_model=stance, reranker=reranker)
