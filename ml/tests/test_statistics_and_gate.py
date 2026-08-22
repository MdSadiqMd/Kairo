from __future__ import annotations

from kairo_ml.evals.gate import evaluate_gate
from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec
from kairo_ml.evals.statistics import (
    paired_bootstrap_delta,
    required_n_for_mde,
    wilson_interval,
)


def test_wilson_interval_bounds() -> None:
    ci = wilson_interval(8, 10)
    assert 0.0 <= ci.low <= ci.point <= ci.high <= 1.0
    assert ci.point == 0.8
    # Zero-n degenerates safely.
    z = wilson_interval(0, 0)
    assert (z.low, z.high) == (0.0, 1.0)


def test_wilson_narrows_with_n() -> None:
    small = wilson_interval(8, 10)
    large = wilson_interval(800, 1000)
    assert (large.high - large.low) < (small.high - small.low)


def test_paired_bootstrap_is_deterministic_and_detects_regression() -> None:
    baseline = [1.0] * 50 + [0.0] * 50
    candidate = [1.0] * 30 + [0.0] * 70  # clearly worse
    d1 = paired_bootstrap_delta(baseline, candidate)
    d2 = paired_bootstrap_delta(baseline, candidate)
    assert d1 == d2  # fixed seed → reproducible verdict
    assert d1.delta < 0
    assert d1.prob_regression > 0.9


def test_required_n_grows_as_mde_shrinks() -> None:
    assert required_n_for_mde(0.72, 0.01) > required_n_for_mde(0.72, 0.05)


def _run(passes: int, n: int, *, safety_flags: int = 0, cost: float = 0.0) -> EvalRun:
    items = []
    for i in range(n):
        items.append(
            ItemResult(
                item_id=str(i),
                passed=i < passes,
                latency_ms=100,
                cost_usd=cost,
                safety_flag=i < safety_flags,
            )
        )
    return EvalRun(eval_run_id="e", suite="s", model="m", model_version="v", items=items)


def test_gate_blocks_on_small_n() -> None:
    spec = PromotionGateSpec(min_pass_rate=0.6, min_n=1000, min_detectable_effect=0.01)
    decision = evaluate_gate(_run(9, 10), spec)
    assert not decision.promotable
    assert any(c.name == "sample_size" and not c.passed for c in decision.checks)


def test_gate_blocks_on_safety_regression() -> None:
    spec = PromotionGateSpec(min_pass_rate=0.0, min_n=10, max_safety_regression=0.0)
    decision = evaluate_gate(_run(100, 100, safety_flags=1), spec)
    assert not decision.promotable
    assert any(c.name == "safety_regression" and not c.passed for c in decision.checks)


def test_gate_passes_clean_candidate() -> None:
    spec = PromotionGateSpec(min_pass_rate=0.6, min_n=10, min_detectable_effect=0.2)
    decision = evaluate_gate(_run(90, 100), spec)
    assert decision.promotable, decision.summary()


def test_gate_blocks_significant_regression_vs_baseline() -> None:
    spec = PromotionGateSpec(
        min_pass_rate=0.0, min_n=10, comparison="paired", min_detectable_effect=0.2
    )
    baseline = _run(90, 100)
    candidate = _run(60, 100)
    decision = evaluate_gate(candidate, spec, baseline=baseline)
    assert not decision.promotable
    assert any(c.name == "no_significant_regression" and not c.passed for c in decision.checks)
