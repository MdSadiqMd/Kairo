from __future__ import annotations

import pytest
from kairo_ml.rag.evals import (
    citation_accuracy,
    faithfulness,
    mean_reciprocal_rank,
    mean_reciprocal_rank_over_queries,
    recall_at_k,
)


def test_recall_at_k() -> None:
    retrieved = ["a", "b", "c", "d"]
    relevant = ["b", "d", "z"]
    assert recall_at_k(retrieved, relevant, k=4) == pytest.approx(2 / 3)
    assert recall_at_k(retrieved, relevant, k=2) == pytest.approx(1 / 3)
    assert recall_at_k(retrieved, [], k=4) == 0.0


def test_mrr_first_relevant_rank() -> None:
    assert mean_reciprocal_rank(["x", "a", "b"], ["a"]) == pytest.approx(1 / 2)
    assert mean_reciprocal_rank(["a", "x"], ["a"]) == pytest.approx(1.0)
    assert mean_reciprocal_rank(["x", "y"], ["a"]) == 0.0


def test_mrr_over_queries() -> None:
    results = [
        (["a", "b"], ["a"]),  # 1.0
        (["x", "b"], ["b"]),  # 0.5
    ]
    assert mean_reciprocal_rank_over_queries(results) == pytest.approx(0.75)
    assert mean_reciprocal_rank_over_queries([]) == 0.0


def test_faithfulness_grounded_answer() -> None:
    context = ["The router uses consistent hashing on a stable prefix key."]
    grounded = "The router uses consistent hashing on the prefix key."
    assert faithfulness(grounded, context) == pytest.approx(1.0)


def test_faithfulness_flags_ungrounded_answer() -> None:
    context = ["The router uses consistent hashing on a stable prefix key."]
    hallucinated = "Bananas contain potassium and grow in tropical rainforests worldwide."
    assert faithfulness(hallucinated, context) < 0.2


def test_faithfulness_empty_answer_is_vacuously_grounded() -> None:
    assert faithfulness("the and of", ["anything"]) == 1.0


def test_citation_accuracy() -> None:
    assert citation_accuracy(["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    assert citation_accuracy(["a", "z"], ["a", "b"]) == pytest.approx(0.5)
    assert citation_accuracy([], ["a"]) == 0.0
