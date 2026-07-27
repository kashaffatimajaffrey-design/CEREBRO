"""
Hybrid retrieval for claim verification.

This is the module that makes CEREBRO's misinformation verdicts citable. v1
asked Gemini for a credibility score and a list of "sources" — and the server's
own response schema admitted what those were:

    sources: { description: "Potential fact-check sources or simulated references." }

Nothing was retrieved. The URLs were generated text. A verdict citing a source
that was never read is worse than a verdict citing nothing, because it invites
trust it hasn't earned.

Here, evidence is retrieved from a real corpus and every citation points at a
document that exists in the database.

## Why hybrid rather than pure vector search

Dense embeddings capture meaning but miss exact tokens — names, dates, figures,
identifiers. A claim like "the 2019 Boeing 737 MAX was grounded in March" needs
"737 MAX" matched *literally*; an embedding will happily return documents about
other aircraft groundings. BM25 nails the rare token and misses paraphrase.
Neither alone is adequate for fact-checking, where the specific number often IS
the claim.

So: run both, fuse with Reciprocal Rank Fusion.

## Why RRF rather than weighted score averaging

BM25 scores are unbounded and corpus-dependent; cosine similarities sit in
[-1,1]. Averaging them requires normalization constants that need retuning
whenever the corpus changes. RRF uses only *rank*, so it is scale-free and has
one parameter (k, conventionally 60). It reliably beats either retriever alone
and usually beats hand-tuned score blending.

    RRF(d) = Σ_retrievers 1 / (k + rank_r(d))
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, Sequence

import numpy as np

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Tokens that carry no discriminative signal. Deliberately short: aggressive
# stoplists remove words like "not", which inverts the meaning of a claim.
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from
by with as is are was were be been being it its he she they them their there
here what which who whom when where how why all any both each few more most
other some such only own same so too very can will just should now
""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS]


# ---------------------------------------------------------------------------
# Documents and results
# ---------------------------------------------------------------------------

@dataclass
class Document:
    id: str
    text: str
    title: str = ""
    url: str | None = None
    domain: str | None = None
    credibility: float = 0.5      # from evidence_sources.credibility_weight
    embedding: np.ndarray | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def searchable(self) -> str:
        return f"{self.title} {self.text}".strip()


@dataclass
class ScoredDocument:
    document: Document
    score: float
    bm25_rank: int | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.document.id,
            "title": self.document.title,
            "url": self.document.url,
            "domain": self.document.domain,
            "credibility": self.document.credibility,
            "score": round(self.score, 6),
            "bm25_rank": self.bm25_rank,
            "vector_rank": self.vector_rank,
            "rerank_score": self.rerank_score,
            "snippet": self.document.text[:300],
        }


# ---------------------------------------------------------------------------
# Embedding interface
# ---------------------------------------------------------------------------

class Embedder(Protocol):
    dim: int
    def encode(self, texts: Sequence[str]) -> np.ndarray: ...


class HashingEmbedder:
    """
    Deterministic bag-of-words embedder with no model download.

    This is NOT a semantic model and is not intended to be — it exists so the
    retrieval pipeline is testable offline, in CI, and on a machine with no GPU,
    and so the system degrades to *worse retrieval* rather than *no retrieval*
    when model weights are unavailable.

    Production path is SentenceTransformerEmbedder below. The interface is
    identical, so swapping is one line.
    """

    def __init__(self, dim: int = 768, seed: int = 42) -> None:
        self.dim = dim
        self.seed = seed

    def _hash_token(self, token: str) -> int:
        h = hashlib.blake2b(token.encode(), digest_size=8,
                            key=self.seed.to_bytes(4, "big")).digest()
        return int.from_bytes(h, "big") % self.dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            counts = Counter(tokenize(text))
            for token, n in counts.items():
                idx = self._hash_token(token)
                # Signed hashing reduces collision bias (Weinberger et al.).
                sign = 1.0 if self._hash_token(token + "#sign") % 2 == 0 else -1.0
                out[i, idx] += sign * (1.0 + math.log(n))
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


class SentenceTransformerEmbedder:
    """
    Production embedder. `BAAI/bge-base-en-v1.5` is 768-dim, matching the
    `vector(768)` column, runs at ~20 ms/document on CPU, and consistently
    outperforms all-MiniLM on retrieval benchmarks at modest extra cost.
    """

    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5") -> None:
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()
        self.model_name = model_name

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return self._model.encode(
            list(texts), normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        ).astype(np.float32)


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------

class BM25Index:
    """
    Okapi BM25. In deployment this is Postgres `ts_rank_cd` over the generated
    `tsv` column; this in-memory implementation exists so retrieval logic can be
    unit-tested without a database, and so the fusion behaviour is verifiable
    independently of Postgres' ranking internals.

    k1 = 1.5 (term-frequency saturation), b = 0.75 (length normalization) are
    the standard defaults and are rarely worth tuning below ~100k documents.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.documents: list[Document] = []
        self._tokenized: list[list[str]] = []
        self._doc_freq: dict[str, int] = defaultdict(int)
        self._avg_len: float = 0.0
        self._idf: dict[str, float] = {}

    def index(self, documents: Sequence[Document]) -> "BM25Index":
        self.documents = list(documents)
        self._tokenized = [tokenize(d.searchable) for d in self.documents]
        self._doc_freq = defaultdict(int)
        for tokens in self._tokenized:
            for token in set(tokens):
                self._doc_freq[token] += 1

        n = max(len(self.documents), 1)
        self._avg_len = sum(len(t) for t in self._tokenized) / n

        # Standard BM25 IDF with the +1 that keeps it non-negative for terms
        # appearing in more than half the corpus.
        self._idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for term, df in self._doc_freq.items()
        }
        return self

    def search(self, query: str, top_k: int = 50) -> list[tuple[int, float]]:
        query_tokens = tokenize(query)
        if not query_tokens or not self.documents:
            return []

        scores = np.zeros(len(self.documents), dtype=np.float64)
        for i, tokens in enumerate(self._tokenized):
            if not tokens:
                continue
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term in query_tokens:
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                idf = self._idf.get(term, 0.0)
                denominator = tf + self.k1 * (1 - self.b + self.b * length / max(self._avg_len, 1e-9))
                score += idf * (tf * (self.k1 + 1)) / denominator
            scores[i] = score

        ranked = np.argsort(-scores)[:top_k]
        return [(int(i), float(scores[i])) for i in ranked if scores[i] > 0]


# ---------------------------------------------------------------------------
# Hybrid retriever
# ---------------------------------------------------------------------------

def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[int]], k: int = 60,
    weights: Sequence[float] | None = None,
) -> dict[int, float]:
    """
    Fuse ranked ID lists. Rank-based, so it needs no score normalization and is
    unaffected by either retriever changing its scoring scale.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    fused: dict[int, float] = defaultdict(float)
    for ranking, weight in zip(rankings, weights):
        for rank, doc_idx in enumerate(ranking, start=1):
            fused[doc_idx] += weight / (k + rank)
    return dict(fused)


class HybridRetriever:
    """
    BM25 + dense vector search, fused with RRF.

    Usage:
        r = HybridRetriever(embedder=HashingEmbedder())
        r.index(documents)
        hits = r.search("did the company recall its product in 2023?", top_k=8)
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        rrf_k: int = 60,
        bm25_weight: float = 1.0,
        vector_weight: float = 1.0,
        candidate_pool: int = 50,
    ) -> None:
        self.embedder = embedder or HashingEmbedder()
        self.rrf_k = rrf_k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.candidate_pool = candidate_pool

        self.bm25 = BM25Index()
        self.documents: list[Document] = []
        self._matrix: np.ndarray | None = None

    def index(self, documents: Sequence[Document]) -> "HybridRetriever":
        self.documents = list(documents)
        if not self.documents:
            self._matrix = None
            return self

        self.bm25.index(self.documents)

        missing = [i for i, d in enumerate(self.documents) if d.embedding is None]
        if missing:
            vectors = self.embedder.encode([self.documents[i].searchable for i in missing])
            for slot, i in enumerate(missing):
                self.documents[i].embedding = vectors[slot]

        self._matrix = np.vstack([d.embedding for d in self.documents])  # type: ignore[misc]
        log.info("indexed %d documents (dim=%d)", len(self.documents), self._matrix.shape[1])
        return self

    def _vector_search(self, query: str, top_k: int) -> list[tuple[int, float]]:
        if self._matrix is None or not len(self.documents):
            return []
        q = self.embedder.encode([query])[0]
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm
        # Rows are already L2-normalized, so the dot product is cosine similarity.
        sims = self._matrix @ q
        ranked = np.argsort(-sims)[:top_k]
        return [(int(i), float(sims[i])) for i in ranked]

    def search(
        self, query: str, top_k: int = 10, *, use_credibility: bool = True,
    ) -> list[ScoredDocument]:
        if not self.documents:
            return []

        bm25_hits = self.bm25.search(query, top_k=self.candidate_pool)
        vector_hits = self._vector_search(query, top_k=self.candidate_pool)

        bm25_ranks = {idx: r for r, (idx, _) in enumerate(bm25_hits, start=1)}
        vector_ranks = {idx: r for r, (idx, _) in enumerate(vector_hits, start=1)}
        bm25_scores = dict(bm25_hits)
        vector_scores = dict(vector_hits)

        fused = reciprocal_rank_fusion(
            [[i for i, _ in bm25_hits], [i for i, _ in vector_hits]],
            k=self.rrf_k, weights=[self.bm25_weight, self.vector_weight],
        )

        results: list[ScoredDocument] = []
        for idx, score in fused.items():
            doc = self.documents[idx]
            final = score
            if use_credibility:
                # Nudge by source credibility without letting it dominate:
                # a highly relevant Wikipedia hit should still outrank a
                # barely-relevant Reuters one.
                final *= (0.5 + 0.5 * doc.credibility)
            results.append(ScoredDocument(
                document=doc,
                score=final,
                bm25_rank=bm25_ranks.get(idx),
                vector_rank=vector_ranks.get(idx),
                bm25_score=bm25_scores.get(idx),
                vector_score=vector_scores.get(idx),
            ))

        results.sort(key=lambda r: -r.score)
        return results[:top_k]


# ---------------------------------------------------------------------------
# Postgres-backed retrieval — the deployment path
# ---------------------------------------------------------------------------

HYBRID_SQL = """
-- Hybrid retrieval executed entirely inside Postgres.
-- Both halves run against the same table, then fuse by rank via RRF.
WITH vector_hits AS (
    SELECT id, url, title, body,
           row_number() OVER (ORDER BY embedding <=> $2::vector) AS rank
    FROM cerebro.documents
    WHERE tenant_id = $1 AND kind = 'evidence' AND embedding IS NOT NULL
    ORDER BY embedding <=> $2::vector
    LIMIT $4
),
lexical_hits AS (
    SELECT id, url, title, body,
           row_number() OVER (ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', $3)) DESC) AS rank
    FROM cerebro.documents
    WHERE tenant_id = $1 AND kind = 'evidence'
      AND tsv @@ plainto_tsquery('english', $3)
    ORDER BY ts_rank_cd(tsv, plainto_tsquery('english', $3)) DESC
    LIMIT $4
),
fused AS (
    SELECT id, SUM(weight) AS rrf_score FROM (
        SELECT id, 1.0 / (60 + rank) AS weight FROM vector_hits
        UNION ALL
        SELECT id, 1.0 / (60 + rank) AS weight FROM lexical_hits
    ) combined
    GROUP BY id
)
SELECT d.id, d.title, d.body, d.source_url,
       f.rrf_score * (0.5 + 0.5 * COALESCE(s.credibility_weight, 0.5)) AS score,
       s.domain, s.publisher, COALESCE(s.credibility_weight, 0.5) AS credibility
FROM fused f
JOIN cerebro.documents d ON d.id = f.id
LEFT JOIN cerebro.evidence_sources s
       ON s.domain = substring(d.source_url from '://(?:www\\.)?([^/]+)')
ORDER BY score DESC
LIMIT $5;
"""
"""SQL for the production path. Params: $1 tenant, $2 query embedding,
$3 query text, $4 candidate pool, $5 final limit."""
