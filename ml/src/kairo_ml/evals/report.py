"""Eval report assembly

Turns an EvalRun + gate decision into the JSON artifact the CLI writes and the
promotion gate consumes: run id, model version, suite, pass flag, and metrics
(pass_rate, p50/p99 latency, cost_per_1k_requests)
"""

from __future__ import annotations

from typing import Any

from kairo_ml.evals.gate import GateDecision
from kairo_ml.evals.models import EvalRun


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


def build_report(run: EvalRun, decision: GateDecision) -> dict[str, Any]:
    latencies = [i.latency_ms for i in run.items]
    total_cost = sum(i.cost_usd for i in run.items)
    cost_per_1k = (total_cost / run.n * 1000) if run.n else 0.0
    return {
        "eval_run_id": run.eval_run_id,
        "suite": run.suite,
        "model": run.model,
        "model_version": run.model_version,
        "router_url": run.router_url,
        "n": run.n,
        "passed": decision.promotable,
        "metrics": {
            "pass_rate": round(run.pass_rate, 4),
            "p50_latency_ms": _percentile(latencies, 0.50),
            "p99_latency_ms": _percentile(latencies, 0.99),
            "cost_per_1k_requests": round(cost_per_1k, 6),
            "safety_regressions": run.safety_regressions,
        },
        "gate": {
            "promotable": decision.promotable,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in decision.checks
            ],
        },
    }
