"""
RAG retrieval and claim-verification tests.

The properties that matter, in order:
  1. Every citation points at a document that was actually retrieved.
  2. No evidence => insufficient_evidence, NOT a confident guess.
  3. Hybrid retrieval beats either retriever alone on exact-token claims.
  4. Source credibility measurably influences ranking.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ml.rag.retrieval import (  # noqa: E402
    Document, BM25Index, HybridRetriever, HashingEmbedder,
    reciprocal_rank_fusion, tokenize,
)
from services.ml.rag.verify import (  # noqa: E402
    ClaimVerifier, LexicalStanceModel, Label, Stance, build_default_verifier,
)

CORPUS = [
    Document(id="d1", title="Boeing 737 MAX grounded worldwide",
             text="Regulators grounded the Boeing 737 MAX in March 2019 after two fatal "
                  "crashes. The FAA issued an emergency order halting all flights.",
             url="https://reuters.com/737max", domain="reuters.com", credibility=0.95),
    Document(id="d2", title="Aviation safety review published",
             text="A review of aviation safety practices examined certification "
                  "procedures for new commercial aircraft across several manufacturers.",
             url="https://apnews.com/aviation", domain="apnews.com", credibility=0.95),
    Document(id="d3", title="Vaccine misinformation debunked",
             text="Claims that vaccines contain tracking microchips are false. No vaccine "
                  "contains any electronic component. This has been repeatedly debunked.",
             url="https://snopes.com/microchip", domain="snopes.com", credibility=0.88),
    Document(id="d4", title="Company quarterly earnings report",
             text="The technology company reported revenue growth of twelve percent in "
                  "the third quarter, beating analyst expectations.",
             url="https://blog.example.com/earnings", domain="blog.example.com",
             credibility=0.3),
    Document(id="d5", title="Electric vehicle sales surge",
             text="Electric vehicle sales rose sharply last year, with battery costs "
                  "falling and charging infrastructure expanding across Europe.",
             url="https://bbc.co.uk/ev", domain="bbc.co.uk", credibility=0.90),
    Document(id="d6", title="Moon landing conspiracy examined",
             text="The Apollo 11 moon landing in 1969 is extensively documented. "
                  "Claims that it was staged are not supported by any credible evidence.",
             url="https://factcheck.org/apollo", domain="factcheck.org", credibility=0.88),
]


# --- tokenization ----------------------------------------------------------

def test_tokenizer_drops_stopwords_but_keeps_negations():
    tokens = tokenize("The company did not recall the product")
    assert "the" not in tokens
    # "not" must survive — dropping it inverts the claim's meaning.
    assert "not" in tokens
    assert "recall" in tokens


# --- BM25 ------------------------------------------------------------------

def test_bm25_finds_exact_rare_tokens():
    idx = BM25Index().index(CORPUS)
    hits = idx.search("Boeing 737 MAX grounded", top_k=3)
    assert hits, "BM25 returned nothing"
    assert CORPUS[hits[0][0]].id == "d1"


def test_bm25_empty_query_and_corpus():
    assert BM25Index().index(CORPUS).search("", top_k=5) == []
    assert BM25Index().index([]).search("anything", top_k=5) == []


# --- RRF -------------------------------------------------------------------

def test_rrf_rewards_agreement_between_retrievers():
    # Doc 5 is ranked #1 by one retriever and #2 by the other; doc 1 is #1 in
    # only one list. Consensus should win.
    fused = reciprocal_rank_fusion([[5, 1, 2], [5, 3, 4]], k=60)
    assert max(fused, key=lambda d: fused[d]) == 5


def test_rrf_weights_apply():
    equal = reciprocal_rank_fusion([[1], [2]], k=60, weights=[1.0, 1.0])
    assert abs(equal[1] - equal[2]) < 1e-9
    skewed = reciprocal_rank_fusion([[1], [2]], k=60, weights=[3.0, 1.0])
    assert skewed[1] > skewed[2]


# --- hybrid retrieval ------------------------------------------------------

def test_hybrid_retrieval_returns_relevant_documents():
    r = HybridRetriever(embedder=HashingEmbedder()).index(CORPUS)
    hits = r.search("Boeing 737 MAX grounded after crashes", top_k=3)
    assert hits
    assert hits[0].document.id == "d1"
    # Both retrievers should have contributed for a claim like this.
    assert hits[0].bm25_rank is not None
    assert hits[0].vector_rank is not None


def test_hybrid_handles_empty_index():
    assert HybridRetriever(embedder=HashingEmbedder()).index([]).search("anything") == []


def test_credibility_influences_ranking():
    """A low-credibility source must rank below a high-credibility one, all else equal."""
    pair = [
        Document(id="lo", title="Vaccine microchip claim", url="https://rumor.example",
                 text="Vaccines contain tracking microchips implanted by governments.",
                 domain="rumor.example", credibility=0.1),
        Document(id="hi", title="Vaccine microchip claim", url="https://snopes.com/x",
                 text="Vaccines contain tracking microchips implanted by governments.",
                 domain="snopes.com", credibility=0.95),
    ]
    # 'lo' is first in the corpus, so it wins the raw retrieval rank tie-break.
    # Credibility weighting must overturn that. (Identical documents can never
    # score exactly equal under RRF, because they occupy adjacent ranks — so the
    # property to assert is that credibility FLIPS the order, not that it ties.)
    r = HybridRetriever(embedder=HashingEmbedder()).index(pair)

    off = r.search("do vaccines contain tracking microchips", top_k=2, use_credibility=False)
    assert off[0].document.id == "lo", "expected raw rank order to favour the first doc"

    on = r.search("do vaccines contain tracking microchips", top_k=2, use_credibility=True)
    assert on[0].document.id == "hi", "credibility failed to outrank the raw tie-break"


# --- stance ----------------------------------------------------------------

def test_lexical_stance_detects_entailment_and_contradiction():
    m = LexicalStanceModel()
    stance, score = m.predict(
        "The Boeing 737 MAX was grounded in 2019",
        "Regulators grounded the Boeing 737 MAX in March 2019 after two crashes.")
    assert stance is Stance.ENTAIL and score > 0.5

    stance, _ = m.predict(
        "Vaccines contain tracking microchips",
        "Claims that vaccines contain tracking microchips are false and debunked.")
    assert stance is Stance.CONTRADICT

    stance, _ = m.predict("The stock market closed higher on Tuesday",
                          "Electric vehicle sales rose sharply last year in Europe.")
    assert stance is Stance.NEUTRAL


# --- verification ----------------------------------------------------------

def _verifier() -> ClaimVerifier:
    r = HybridRetriever(embedder=HashingEmbedder()).index(CORPUS)
    return ClaimVerifier(retriever=r, stance_model=LexicalStanceModel(), min_confidence=0.1)


def test_supported_claim_gets_real_citations():
    v = _verifier().verify("The Boeing 737 MAX was grounded in March 2019")
    assert v.label in (Label.SUPPORTED, Label.DISPUTED)
    assert v.evidence, "a verdict with no evidence is the v1 failure mode"
    assert v.citations, "no citations produced"
    # THE critical property: every citation must exist in the corpus.
    corpus_urls = {d.url for d in CORPUS}
    for url in v.citations:
        assert url in corpus_urls, f"HALLUCINATED CITATION: {url}"


def test_refuted_claim_is_refuted():
    v = _verifier().verify("Vaccines contain tracking microchips")
    assert v.label is Label.REFUTED, f"got {v.label} (support={v.support_weight:.3f}, refute={v.refute_weight:.3f})"
    assert v.refute_weight > v.support_weight


def test_unrelated_claim_returns_insufficient_not_a_guess():
    """
    The single most important behaviour in this module. v1 always produced a
    confident credibilityScore, even with nothing to go on.
    """
    r = HybridRetriever(embedder=HashingEmbedder()).index(CORPUS)
    verifier = ClaimVerifier(retriever=r, stance_model=LexicalStanceModel(),
                             min_confidence=0.55)
    v = verifier.verify("Zorbulon nine hyperdrive quintessence flarn wobbleplex")
    assert v.label is Label.INSUFFICIENT
    assert v.confidence < 0.55


def test_empty_corpus_returns_insufficient_with_no_citations():
    r = HybridRetriever(embedder=HashingEmbedder()).index([])
    v = ClaimVerifier(retriever=r, stance_model=LexicalStanceModel()).verify("anything")
    assert v.label is Label.INSUFFICIENT
    assert v.citations == []
    assert v.confidence == 0.0


def test_empty_claim_handled():
    for bad in ("", "   "):
        v = _verifier().verify(bad)
        assert v.label is Label.INSUFFICIENT


def test_verdict_records_model_versions():
    """A verdict that cannot name the models that produced it is not auditable."""
    v = _verifier().verify("The Boeing 737 MAX was grounded in March 2019")
    assert v.model_versions.get("stance")
    assert v.model_versions.get("embedder")


def test_verdict_serializes_with_evidence():
    d = _verifier().verify("The Boeing 737 MAX was grounded in March 2019").as_dict()
    for key in ("claim", "label", "confidence", "evidence", "citations", "model_versions"):
        assert key in d
    if d["evidence"]:
        for key in ("url", "stance", "nli_score", "credibility"):
            assert key in d["evidence"][0]


def test_build_default_verifier_falls_back_offline():
    """No transformers installed here — must degrade, not crash."""
    v = build_default_verifier(CORPUS, prefer_transformers=True)
    out = v.verify("The Boeing 737 MAX was grounded in March 2019")
    assert out.label is not None


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
