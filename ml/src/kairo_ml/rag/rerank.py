"""Rerankers

After fusion produces a candidate set, a reranker re-scores each candidate against
the query with a more expensive, query-aware model and keeps the best ones. The
Reranker protocol has two implementations:
- `HeuristicReranker` — pure Python; scores by query-term coverage and lexical
  overlap. Used in tests and as an offline fallback when no model is available
- `CrossEncoderReranker` — a cross-encoder (or configured model-derived scorer)
  that jointly encodes (query, chunk) pairs. Lazily imports transformers so
  this module loads offline without it
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from kairo_ml.rag.bm25 import tokenize
from kairo_ml.rag.chunker import Chunk


class Reranker(Protocol):
    """Re-scores candidate chunks against a query, best first"""

    def rerank(
        self, query: str, candidates: Sequence[Chunk], *, top_k: int
    ) -> list[tuple[Chunk, float]]: ...


class HeuristicReranker:
    """Lexical reranker: query-term coverage blended with overlap density.

    coverage is the fraction of distinct query terms present in the chunk —
    the dominant signal, since a chunk answering the query should mention most of
    its terms. density is the fraction of chunk tokens that are query terms,
    a tie-breaker that favors focused chunks over long ones that merely happen to
    contain the terms. The blend weights coverage 0.7 / density 0.3
    """

    def __init__(self, coverage_weight: float = 0.7) -> None:
        if not 0.0 <= coverage_weight <= 1.0:
            raise ValueError("coverage_weight must be in [0, 1]")
        self.coverage_weight = coverage_weight

    def _score(self, query_terms: set[str], chunk: Chunk) -> float:
        if not query_terms:
            return 0.0
        chunk_tokens = tokenize(chunk.indexable_text())
        if not chunk_tokens:
            return 0.0
        chunk_terms = set(chunk_tokens)
        matched = query_terms & chunk_terms
        coverage = len(matched) / len(query_terms)
        density = sum(1 for t in chunk_tokens if t in query_terms) / len(chunk_tokens)
        return self.coverage_weight * coverage + (1.0 - self.coverage_weight) * density

    def rerank(
        self, query: str, candidates: Sequence[Chunk], *, top_k: int
    ) -> list[tuple[Chunk, float]]:
        query_terms = set(tokenize(query))
        scored = [(chunk, self._score(query_terms, chunk)) for chunk in candidates]
        scored.sort(key=lambda pair: (-pair[1], pair[0].chunk_id))
        return scored[:top_k]


class CrossEncoderReranker:
    """Cross-encoder reranker (lazy transformers import)

    Loads a sequence-classification cross-encoder on first use and scores each
    (query, chunk) pair jointly. The model load is deferred so importing this
    module offline never requires transformers or torch
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2") -> None:
        self.model_name = model_name
        self._model: Any = None
        self._tokenizer: Any = None

    def _ensure_model(self) -> tuple[Any, Any]:
        if self._model is None:
            import torch  # noqa: F401 - imported for side effect / availability
            from transformers import (
                AutoModelForSequenceClassification,
                AutoTokenizer,
            )

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            self._model.eval()
        return self._model, self._tokenizer

    def rerank(
        self, query: str, candidates: Sequence[Chunk], *, top_k: int
    ) -> list[tuple[Chunk, float]]:
        import torch

        model, tokenizer = self._ensure_model()
        pairs = [(query, chunk.indexable_text()) for chunk in candidates]
        features = tokenizer(
            [q for q, _ in pairs],
            [d for _, d in pairs],
            padding=True,
            truncation=True,
            return_tensors="pt",
        )
        with torch.no_grad():
            logits = model(**features).logits.squeeze(-1)
        scores = logits.tolist()
        if not isinstance(scores, list):
            scores = [scores]
        ranked = list(zip(candidates, (float(s) for s in scores), strict=True))
        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked[:top_k]
