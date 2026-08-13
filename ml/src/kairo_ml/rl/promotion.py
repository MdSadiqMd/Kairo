"""Promotion decision logic for online RL candidates

Compares candidate and baseline eval results, produces a structured decision
with full evidence, and writes it to storage for audit
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kairo_common import get_logger

from kairo_ml.evals.gate import GateDecision, evaluate_gate
from kairo_ml.evals.models import EvalRun, PromotionGateSpec

log = get_logger("promotion")


@dataclass
class DeltaStats:
    """Statistical comparison between candidate and baseline"""

    pass_rate_delta: float  # candidate - baseline
    cost_delta_pct: float  # (candidate - baseline) / baseline * 100
    latency_p99_delta_ms: int  # candidate - baseline
    safety_regression_count: int  # items that regressed on safety


@dataclass
class PromotionDecision:
    """Full evidence bundle for a promotion decision"""

    accepted: bool
    reason: str
    candidate_report_uri: str | None = None
    baseline_report_uri: str | None = None
    delta_stats: DeltaStats | None = None
    gate_decision: GateDecision | None = None
    timestamp: int = field(default_factory=lambda: int(time.time()))
    candidate_version: str = ""
    baseline_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        result: dict[str, Any] = {
            "accepted": self.accepted,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "candidate_version": self.candidate_version,
            "baseline_version": self.baseline_version,
        }
        if self.candidate_report_uri:
            result["candidate_report_uri"] = self.candidate_report_uri
        if self.baseline_report_uri:
            result["baseline_report_uri"] = self.baseline_report_uri
        if self.delta_stats:
            result["delta_stats"] = asdict(self.delta_stats)
        if self.gate_decision:
            result["gate_summary"] = self.gate_decision.summary()
            result["gate_checks"] = [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.gate_decision.checks
            ]
        return result


def compute_delta_stats(candidate: EvalRun, baseline: EvalRun) -> DeltaStats:
    """Compute delta statistics between candidate and baseline"""
    pass_rate_delta = candidate.pass_rate - baseline.pass_rate

    if baseline.mean_cost_usd > 0:
        cost_delta_pct = (
            (candidate.mean_cost_usd - baseline.mean_cost_usd) / baseline.mean_cost_usd * 100
        )
    else:
        cost_delta_pct = 0.0

    latency_delta = candidate.p99_latency_ms() - baseline.p99_latency_ms()

    return DeltaStats(
        pass_rate_delta=pass_rate_delta,
        cost_delta_pct=cost_delta_pct,
        latency_p99_delta_ms=latency_delta,
        safety_regression_count=candidate.safety_regressions,
    )


def evaluate_for_promotion(
    candidate_eval: EvalRun,
    gate_spec: PromotionGateSpec,
    baseline_eval: EvalRun | None = None,
) -> PromotionDecision:
    """Compare candidate vs baseline and return a promotion decision

    Args:
        candidate_eval: Eval results for the candidate model
        gate_spec: Promotion gate specification with thresholds
        baseline_eval: Eval results for the baseline model, or None for no-baseline mode

    Returns:
        PromotionDecision with full evidence
    """
    decision = evaluate_gate(candidate_eval, gate_spec, baseline=baseline_eval)

    delta_stats = None
    if baseline_eval is not None:
        delta_stats = compute_delta_stats(candidate_eval, baseline_eval)

    if decision.promotable:
        reason = "all_gates_passed"
    else:
        failed = [c.name for c in decision.checks if not c.passed]
        reason = f"gate_failed:{','.join(failed)}"

    return PromotionDecision(
        accepted=decision.promotable,
        reason=reason,
        delta_stats=delta_stats,
        gate_decision=decision,
        candidate_version=candidate_eval.model_version,
        baseline_version=baseline_eval.model_version if baseline_eval else "",
    )


def write_promotion_decision(decision: PromotionDecision, output_uri: str) -> None:
    """Write the promotion decision to S3 or local filesystem

    Args:
        decision: The promotion decision to write
        output_uri: s3://bucket/key or local file path
    """
    data = json.dumps(decision.to_dict(), indent=2, sort_keys=True).encode()

    if output_uri.startswith("s3://"):
        import boto3

        bucket, key = output_uri.removeprefix("s3://").split("/", 1)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data)
        log.info("wrote promotion decision to S3", extra={"uri": output_uri})
    else:
        path = Path(output_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        log.info("wrote promotion decision to file", extra={"path": str(path)})


def write_eval_report(eval_run: EvalRun, output_uri: str) -> str:
    """Write an eval run report to S3 or local filesystem

    Args:
        eval_run: The eval run to write
        output_uri: s3://bucket/key or local file path

    Returns:
        The output URI (for reference in PromotionDecision)
    """
    data = json.dumps(eval_run.model_dump(), indent=2, sort_keys=True).encode()

    if output_uri.startswith("s3://"):
        import boto3

        bucket, key = output_uri.removeprefix("s3://").split("/", 1)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data)
    else:
        path = Path(output_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    return output_uri
