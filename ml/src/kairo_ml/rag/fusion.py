"""Reciprocal Rank Fusion.

RRF merges the ranked result lists from BM25 and the vector index into a single
ranking without needing the two scores to be comparable (BM25 scores and cosine
similarities live on different, unnormalized scales). Each list contributes to a
document's fused score by the rank it assigns, not the raw score:

    rrf(d) = sum over lists L of  weight(L) / (k + rank_L(d))

where rank_L(d) is d's 0-based position in list L and k is a smoothing
constant (60 is the standard default). A large k flattens the contribution of
top ranks; a small k sharpens it. Documents absent from a list contribute
nothing from that list
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[str]],
    *,
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """Fuse ranked id lists into one ranking, highest fused score first

    Args:
        result_lists: each inner sequence is ids ordered best-first
        k: RRF smoothing constant
        weights: optional per-list weights (defaults to 1.0 each)
    """
    if weights is None:
        weights = [1.0] * len(result_lists)
    if len(weights) != len(result_lists):
        raise ValueError("weights must match result_lists length")

    fused: dict[str, float] = defaultdict(float)
    for weight, ranking in zip(weights, result_lists, strict=True):
        for rank, doc_id in enumerate(ranking):
            fused[doc_id] += weight / (k + rank)

    merged = list(fused.items())
    # Sort by fused score desc; break ties on id for deterministic output.
    merged.sort(key=lambda pair: (-pair[1], pair[0]))
    return merged
