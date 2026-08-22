from __future__ import annotations

from kairo_ml.rag.bm25 import BM25Index, tokenize


def test_tokenize_lowercases_and_splits() -> None:
    assert tokenize("Hello, World! API-key_42") == ["hello", "world", "api", "key", "42"]


def test_bm25_ranks_relevant_doc_first() -> None:
    index = BM25Index()
    index.add("d1", "the quick brown fox jumps over the lazy dog")
    index.add("d2", "kubernetes autoscaling and pod scheduling on aws")
    index.add("d3", "a treatise on the migratory patterns of arctic birds")

    results = index.search("kubernetes pod autoscaling", k=3)
    assert results, "expected at least one hit"
    assert results[0][0] == "d2"


def test_bm25_omits_zero_score_docs() -> None:
    index = BM25Index()
    index.add("d1", "alpha beta gamma")
    index.add("d2", "delta epsilon zeta")

    results = index.search("alpha", k=10)
    assert [doc_id for doc_id, _ in results] == ["d1"]


def test_bm25_rare_term_outranks_common_term() -> None:
    index = BM25Index()
    # "the" appears everywhere (low idf); "quasar" is rare (high idf).
    for i in range(5):
        index.add(f"common{i}", "the the the the the the")
    index.add("rare", "the quasar the")

    results = index.search("the quasar", k=6)
    assert results[0][0] == "rare"


def test_bm25_length_normalization_prefers_focused_doc() -> None:
    index = BM25Index()
    index.add("short", "climate policy")
    index.add(
        "long",
        "climate policy " + " ".join(f"filler{i}" for i in range(200)),
    )
    results = index.search("climate policy", k=2)
    # With b>0, the shorter doc gets the length-normalization boost.
    assert results[0][0] == "short"
