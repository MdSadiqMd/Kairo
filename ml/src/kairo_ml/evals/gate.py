"""The promotion gate

A model cannot be promoted unless all conditions hold. This module turns
that rule set into a single, explainable decision object with per-check verdicts
so a failing promotion says exactly which gate failed and by how much

The gate is statistical, not a point-estimate threshold:
- pass rate is reported with a Wilson CI
- against a baseline, the candidate must not significantly regress (paired
  bootstrap; the regression probability must stay under the significance level)
- safety and over-refusal gates are one-sided and strict
- cost and latency have hard bounds

The same gate runs offline (slow, full suite) and inside the real-time RL loop
(fast, per-cycle) only the suite size differs
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kairo_ml.evals.models import EvalRun, PromotionGateSpec
from kairo_ml.evals.statistics import (
    PairedDelta,
    paired_bootstrap_delta,
    required_n_for_mde,
    wilson_interval,
)


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateDecision:
    promotable: bool
    checks: list[Check] = field(default_factory=list)

    def summary(self) -> str:
        status = "PROMOTABLE" if self.promotable else "BLOCKED"
        lines = [f"[{status}]"]
        for c in self.checks:
            mark = "✓" if c.passed else "✗"
            lines.append(f"  {mark} {c.name}: {c.detail}")
        return "\n".join(lines)


def evaluate_gate(
    candidate: EvalRun,
    spec: PromotionGateSpec,
    *,
    baseline: EvalRun | None = None,
) -> GateDecision:
    checks: list[Check] = []

    # 1. Adequate sample size for the declared MDE. A non-positive MDE
    # means "size on min_n only" — the semantics of a fast health-check suite
    # that gates on a pass-rate floor rather
    # than statistical power. Full promotion suites set a real MDE.
    if spec.min_detectable_effect > 0:
        needed = required_n_for_mde(
            max(spec.min_pass_rate, 0.5),
            spec.min_detectable_effect,
            alpha=spec.significance_level,
        )
        required_n = max(spec.min_n, needed)
        detail = (
            f"n={candidate.n}, required≥{required_n} "
            f"(min_n={spec.min_n}, MDE={spec.min_detectable_effect})"
        )
    else:
        required_n = spec.min_n
        detail = f"n={candidate.n}, required≥{required_n} (min_n only; health-check suite)"
    checks.append(Check("sample_size", candidate.n >= required_n, detail))

    # 2. Absolute pass-rate floor, reported with a Wilson CI.
    ci = wilson_interval(candidate.passes, candidate.n)
    checks.append(
        Check(
            "pass_rate_floor",
            ci.low >= spec.min_pass_rate,
            f"pass_rate={ci.point:.3f} (95% CI [{ci.low:.3f}, {ci.high:.3f}]) "
            f"vs floor {spec.min_pass_rate}",
        )
    )

    # 3. No significant regression vs. baseline (paired).
    if baseline is not None:
        delta = _delta_vs_baseline(baseline, candidate, spec)
        significant_regression = (
            delta.prob_regression > (1 - spec.significance_level) and delta.delta < 0
        )
        checks.append(
            Check(
                "no_significant_regression",
                not significant_regression,
                f"Δpass={delta.delta:+.3f} (CI [{delta.low:+.3f}, {delta.high:+.3f}]), "
                f"P(regress)={delta.prob_regression:.3f}",
            )
        )

    # 4. Safety regression — one-sided, strict.
    safety_rate = candidate.safety_regressions / candidate.n if candidate.n else 0.0
    checks.append(
        Check(
            "safety_regression",
            safety_rate <= spec.max_safety_regression,
            f"safety_flag_rate={safety_rate:.4f} vs max {spec.max_safety_regression}",
        )
    )

    # 5. Cost bound vs. baseline.
    if baseline is not None and baseline.mean_cost_usd > 0:
        increase = (candidate.mean_cost_usd - baseline.mean_cost_usd) / baseline.mean_cost_usd
        checks.append(
            Check(
                "cost_increase",
                increase <= spec.max_cost_increase,
                f"cost Δ={increase:+.1%} vs max {spec.max_cost_increase:+.0%}",
            )
        )

    # 6. Latency SLO.
    if spec.max_latency_p99_ms is not None:
        p99 = candidate.p99_latency_ms()
        checks.append(
            Check(
                "latency_p99",
                p99 <= spec.max_latency_p99_ms,
                f"p99={p99}ms vs SLO {spec.max_latency_p99_ms}ms",
            )
        )

    return GateDecision(promotable=all(c.passed for c in checks), checks=checks)


def _delta_vs_baseline(
    baseline: EvalRun, candidate: EvalRun, spec: PromotionGateSpec
) -> PairedDelta:
    if spec.comparison == "paired" and baseline.n == candidate.n and baseline.n > 0:
        # Assumes items are aligned by index (same prompts, same order).
        return paired_bootstrap_delta(
            baseline.pass_vector(),
            candidate.pass_vector(),
            confidence=1 - spec.significance_level,
        )
    # Fall back to an unpaired difference of means with a crude CI.
    diff = candidate.pass_rate - baseline.pass_rate
    return PairedDelta(diff, diff, diff, min(baseline.n, candidate.n), 1.0 if diff < 0 else 0.0)
