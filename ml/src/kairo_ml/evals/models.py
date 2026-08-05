"""Eval data models

These mirror the registry YAML and the eval-run output. Kept as
pydantic models so the eval_api service, the CLI, and the promotion gate all
share one validated shape
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Comparison = Literal["paired", "unpaired"]


class PromotionGateSpec(BaseModel):
    """Thresholds a candidate must clear vs. the baseline"""

    min_pass_rate: float = 0.0
    baseline_model: str | None = None
    comparison: Comparison = "paired"
    significance_level: float = 0.05
    min_detectable_effect: float = 0.01
    min_n: int = 100
    max_safety_regression: float = 0.005  # one-sided, strict
    max_cost_increase: float = 0.15
    max_latency_p99_ms: int | None = None


class EvalSpec(BaseModel):
    """A versioned registry entry"""

    id: str
    name: str
    type: str
    visibility: Literal["private", "public"] = "private"
    dataset_uri: str
    runner: str
    scorer: str
    timeout_seconds: int = 1800
    network_policy: Literal["restricted", "allowlist", "open"] = "restricted"
    git_history_policy: Literal["reinitialized", "as_is"] = "reinitialized"
    metrics: list[str] = Field(default_factory=list)
    promotion_gate: PromotionGateSpec = Field(default_factory=PromotionGateSpec)


class ItemResult(BaseModel):
    item_id: str
    passed: bool
    score: float = 0.0
    latency_ms: int = 0
    cost_usd: float = 0.0
    safety_flag: bool = False


class EvalRun(BaseModel):
    """Output of running an EvalSpec against a model"""

    eval_run_id: str
    suite: str
    model: str
    model_version: str
    router_url: str | None = None
    items: list[ItemResult] = Field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.items)

    @property
    def passes(self) -> int:
        return sum(1 for i in self.items if i.passed)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.n if self.n else 0.0

    @property
    def safety_regressions(self) -> int:
        return sum(1 for i in self.items if i.safety_flag)

    @property
    def mean_cost_usd(self) -> float:
        return sum(i.cost_usd for i in self.items) / self.n if self.n else 0.0

    def p99_latency_ms(self) -> int:
        if not self.items:
            return 0
        ordered = sorted(i.latency_ms for i in self.items)
        idx = min(len(ordered) - 1, int(0.99 * len(ordered)))
        return ordered[idx]

    def pass_vector(self) -> list[float]:
        return [1.0 if i.passed else 0.0 for i in self.items]
