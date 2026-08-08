"""Retrieval evaluation metrics

Pure-python metrics for offline evaluation of the hybrid retriever:
- `recall_at_k` — of the relevant chunks, how many appear in the top-k
- `mean_reciprocal_rank` — how high the first relevant chunk ranks
- `faithfulness` — how much of an answer is lexically grounded in the retrieved
  context (a proxy for "the answer is supported by the context, not hallucinated")
- `citation_accuracy` — of the chunks the answer cites, how many are actually
  relevant

The faithfulness metric is deliberately a lexical grounding heuristic, not a model
judge: it is the cheap, deterministic gate that runs in CI. A model-based
faithfulness judge complements it, but this catches gross ungroundedness for free
"""

from __future__ import annotations

from collections.abc import Sequence

from kairo_ml.rag.bm25 import tokenize

# Common function words carry no grounding signal, excluding them keeps the
# faithfulness ratio from being inflated by "the/of/and" overlap
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "that",
        "the",
        "to",
        "was",
        "were",
        "with",
        "this",
        "these",
        "those",
        "or",
        "but",
        "not",
        "have",
        "had",
    }
)


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Sequence[str], k: int) -> float:
    """Fraction of relevant ids present in the top-k retrieved ids"""
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(relevant & top_k) / len(relevant)


def mean_reciprocal_rank(retrieved_ids: Sequence[str], relevant_ids: Sequence[str]) -> float:
    """Reciprocal of the 1-based rank of the first relevant id; 0 if none found"""
    relevant = set(relevant_ids)
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def mean_reciprocal_rank_over_queries(
    results: Sequence[tuple[Sequence[str], Sequence[str]]],
) -> float:
    """Average MRR across (retrieved_ids, relevant_ids) query pairs"""
    if not results:
        return 0.0
    return sum(mean_reciprocal_rank(r, rel) for r, rel in results) / len(results)


def _content_terms(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in _STOPWORDS}


def faithfulness(answer: str, contexts: Sequence[str]) -> float:
    """Fraction of the answer's content terms grounded in the retrieved context.

    A value near 1.0 means nearly every meaningful token in the answer also
    appears in the supplied context (well-grounded); a low value flags an answer
    that introduces terms absent from the retrieved material (possible
    hallucination). An answer with no content terms scores 1.0 vacuously
    """
    answer_terms = _content_terms(answer)
    if not answer_terms:
        return 1.0
    context_terms: set[str] = set()
    for context in contexts:
        context_terms |= _content_terms(context)
    grounded = answer_terms & context_terms
    return len(grounded) / len(answer_terms)


def citation_accuracy(cited_ids: Sequence[str], relevant_ids: Sequence[str]) -> float:
    """Precision of citations: fraction of cited ids that are actually relevant"""
    if not cited_ids:
        return 0.0
    relevant = set(relevant_ids)
    correct = sum(1 for cid in cited_ids if cid in relevant)
    return correct / len(cited_ids)
