from __future__ import annotations

from kairo_ml.rag.fusion import reciprocal_rank_fusion


def test_rrf_rewards_agreement_across_lists() -> None:
    bm25 = ["a", "b", "c"]
    vector = ["b", "c", "d"]
    fused = reciprocal_rank_fusion([bm25, vector], k=60)
    ids = [doc_id for doc_id, _ in fused]
    # "b" ranks high in both lists (1 and 0) -> highest fused score; "a" appears
    # in only one list so it can't beat a doc ranked well in both.
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c", "d"}


def test_rrf_merges_disjoint_lists() -> None:
    fused = reciprocal_rank_fusion([["a"], ["b"]], k=60)
    assert {doc_id for doc_id, _ in fused} == {"a", "b"}


def test_rrf_top_of_both_lists_wins() -> None:
    fused = reciprocal_rank_fusion([["x", "y", "z"], ["x", "z", "y"]], k=60)
    assert fused[0][0] == "x"


def test_rrf_weights_bias_a_list() -> None:
    lists = [["a", "b"], ["b", "a"]]
    weighted = reciprocal_rank_fusion(lists, k=60, weights=[5.0, 1.0])
    assert weighted[0][0] == "a"


def test_rrf_scores_descend_and_are_deterministic() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["c", "b", "a"]], k=10)
    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)
    # Deterministic tie-break on id when scores are equal.
    assert reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60) == reciprocal_rank_fusion(
        [["a", "b"], ["b", "a"]], k=60
    )
