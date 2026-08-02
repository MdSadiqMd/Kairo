"""Live per-route cost tracking

Accumulates token usage by route and blends it against measured per-route
prices to produce $/request and a blended cost, so the platform can alert on
margin drift and validate that routing actually saves money
Fed by the same InferenceEvent stream the data plane consumes
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from kairo_ml.cost.model import RoutePrice


@dataclass
class _RouteAccum:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class CostReport:
    total_cost_usd: float
    total_requests: int
    blended_cost_per_request: float
    per_route: dict[str, dict[str, float]] = field(default_factory=dict)


class CostTracker:
    def __init__(self, prices: dict[str, RoutePrice]) -> None:
        self._prices = prices
        self._acc: dict[str, _RouteAccum] = defaultdict(_RouteAccum)

    def record(self, *, route: str, input_tokens: int, output_tokens: int) -> float:
        """Record one request and return its cost. Unknown routes cost 0 but are
        still counted so their share is visible."""
        acc = self._acc[route]
        acc.requests += 1
        acc.input_tokens += input_tokens
        acc.output_tokens += output_tokens
        price = self._prices.get(route)
        cost = price.request_cost(input_tokens, output_tokens) if price else 0.0
        acc.cost_usd += cost
        return cost

    def report(self) -> CostReport:
        total_cost = sum(a.cost_usd for a in self._acc.values())
        total_reqs = sum(a.requests for a in self._acc.values())
        per_route = {
            route: {
                "requests": a.requests,
                "cost_usd": round(a.cost_usd, 6),
                "cost_per_request": round(a.cost_usd / a.requests, 6) if a.requests else 0.0,
                "input_tokens": a.input_tokens,
                "output_tokens": a.output_tokens,
            }
            for route, a in self._acc.items()
        }
        return CostReport(
            total_cost_usd=round(total_cost, 6),
            total_requests=total_reqs,
            blended_cost_per_request=round(total_cost / total_reqs, 6) if total_reqs else 0.0,
            per_route=per_route,
        )
