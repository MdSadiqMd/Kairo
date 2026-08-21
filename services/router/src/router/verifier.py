"""Verifier / reranker client for test-time compute.

In deep/max modes the router samples N candidates and asks a verifier
model to score and rerank them, returning the best (or escalating). The verifier
is a separate configured model-derived scorer served with vLLM's scoring/reranking API.
If no verifier is configured or it errors, we degrade gracefully to the
first candidate rather than failing the request.
"""

from __future__ import annotations

from typing import Any

import httpx
from kairo_common import get_logger

log = get_logger(__name__)


class VerifierClient:
    def __init__(self, client: httpx.AsyncClient, *, timeout_s: float = 10.0) -> None:
        self._client = client
        self._timeout = timeout_s

    async def rerank(
        self, endpoint: str, *, prompt: str, candidates: list[str], served_model_id: str
    ) -> tuple[int, list[float]]:
        """Return (best_index, scores). Falls back to index 0 on any failure."""
        if len(candidates) <= 1:
            return 0, [1.0] * len(candidates)
        try:
            resp = await self._client.post(
                f"{endpoint.rstrip('/')}/v1/score",
                json={
                    "model": served_model_id,
                    "text_1": prompt,
                    "text_2": candidates,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            scores = _extract_scores(resp.json(), len(candidates))
        except Exception:
            log.warning("verifier unavailable; returning first candidate", exc_info=True)
            return 0, [0.0] * len(candidates)
        best = max(range(len(scores)), key=lambda i: scores[i])
        return best, scores


def _extract_scores(payload: dict[str, Any], n: int) -> list[float]:
    data = payload.get("data", [])
    scores = [float(item.get("score", 0.0)) for item in data]
    if len(scores) != n:
        # Shape mismatch — treat as no signal rather than trusting partial data.
        return [0.0] * n
    return scores
