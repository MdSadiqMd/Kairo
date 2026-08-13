"""Real candidate evaluator for online RL

Replaces the synthetic `evaluator_from_env()` with actual evaluation against
candidate and baseline model endpoints using the smoke suite

Local mode: When KAIRO_ENV=local or mode="local", the evaluator can work
without a full inference stack by using a local vLLM server or mock responses
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from kairo_common import get_logger

from kairo_ml.evals.models import EvalRun, EvalSpec, ItemResult
from kairo_ml.evals.registry import DEFAULT_REGISTRY_DIR, EvalRegistry
from kairo_ml.evals.runners import SmokeRunner

log = get_logger("candidate-evaluator")


def _is_local_mode() -> bool:
    """Detect if we're running in local/MiniStack mode."""
    env = os.environ.get("KAIRO_ENV", "")
    return env == "local" or "localhost" in os.environ.get("ONLINE_RL_CANDIDATE_ENDPOINT", "")


@dataclass
class EvalConfig:
    """Configuration for running candidate evaluation"""

    suite_id: str = "smoke_v1"
    model_name: str = "model-32b"
    registry_dir: str | Path = DEFAULT_REGISTRY_DIR
    timeout_s: float = 60.0


class CandidateEvaluator:
    """Evaluates a candidate model against a baseline using the smoke suite

    For online RL, both endpoints are vLLM deployments. The evaluator runs the
    same suite against both, enabling paired comparison in the gate
    """

    def __init__(
        self,
        candidate_endpoint: str,
        baseline_endpoint: str | None = None,
        config: EvalConfig | None = None,
        api_key: str | None = None,
    ) -> None:
        self.candidate_endpoint = candidate_endpoint
        self.baseline_endpoint = baseline_endpoint
        self.config = config or EvalConfig()
        self.api_key = api_key
        self._registry: EvalRegistry | None = None

    @property
    def registry(self) -> EvalRegistry:
        if self._registry is None:
            self._registry = EvalRegistry.load(self.config.registry_dir)
        return self._registry

    @property
    def spec(self) -> EvalSpec:
        return self.registry.get(self.config.suite_id)

    def _create_runner(self, endpoint: str) -> SmokeRunner:
        return SmokeRunner.for_router(
            endpoint,
            self.config.model_name,
            api_key=self.api_key,
            timeout_s=self.config.timeout_s,
        )

    def evaluate_candidate(self, model_version: str) -> EvalRun:
        """Run the eval suite against the candidate endpoint"""
        log.info(
            "evaluating candidate",
            extra={"endpoint": self.candidate_endpoint, "suite": self.config.suite_id},
        )
        runner = self._create_runner(self.candidate_endpoint)
        return runner.run(
            self.spec,
            model=self.config.model_name,
            model_version=model_version,
            router_url=self.candidate_endpoint,
        )

    def evaluate_baseline(self, model_version: str = "baseline") -> EvalRun | None:
        """Run the eval suite against the baseline endpoint, if configured"""
        if not self.baseline_endpoint:
            return None
        log.info(
            "evaluating baseline",
            extra={"endpoint": self.baseline_endpoint, "suite": self.config.suite_id},
        )
        runner = self._create_runner(self.baseline_endpoint)
        return runner.run(
            self.spec,
            model=self.config.model_name,
            model_version=model_version,
            router_url=self.baseline_endpoint,
        )

    def evaluate_both(
        self, candidate_version: str, baseline_version: str = "baseline"
    ) -> tuple[EvalRun, EvalRun | None]:
        """Evaluate both candidate and baseline, returning both results"""
        candidate_eval = self.evaluate_candidate(candidate_version)
        baseline_eval = self.evaluate_baseline(baseline_version)
        return candidate_eval, baseline_eval


EvalMode = Literal["http", "local"]


def run_candidate_eval(
    candidate_url: str,
    baseline_url: str | None = None,
    suite_id: str = "smoke_v1",
    api_key: str | None = None,
    model_name: str = "model-32b",
    candidate_version: str = "candidate",
    *,
    mode: EvalMode = "http",
) -> tuple[EvalRun, EvalRun | None]:
    """Convenience function to run candidate evaluation

    Args:
        candidate_url: URL of the candidate model endpoint (vLLM or router)
        baseline_url: URL of the baseline model endpoint, or None to skip baseline
        suite_id: Eval suite to run (default: smoke_v1)
        api_key: API key for authenticating with the endpoints
        model_name: Model name to pass in chat completions
        candidate_version: Version string for the candidate
        mode: "http" for router/vLLM endpoint, "local" for direct model call (future)

    Returns:
        Tuple of (candidate_eval, baseline_eval). baseline_eval is None if baseline_url is None
    """
    if mode == "local" or _is_local_mode():
        return _run_local_eval(suite_id, model_name, candidate_version)

    config = EvalConfig(suite_id=suite_id, model_name=model_name)
    evaluator = CandidateEvaluator(
        candidate_endpoint=candidate_url,
        baseline_endpoint=baseline_url,
        config=config,
        api_key=api_key,
    )
    return evaluator.evaluate_both(candidate_version)


def evaluator_from_config() -> CandidateEvaluator:
    """Create a CandidateEvaluator from environment variables

    Environment variables:
        ONLINE_RL_CANDIDATE_ENDPOINT: URL of the candidate endpoint (required for real mode)
        ONLINE_RL_BASELINE_ENDPOINT: URL of the baseline endpoint (optional)
        ONLINE_RL_EVAL_SUITE: Eval suite ID (default: smoke_v1)
        ONLINE_RL_MODEL: Model name (default: model-32b)
        ONLINE_RL_API_KEY: API key for endpoints
        ONLINE_RL_REGISTRY_DIR: Path to eval registry (default: ml/evals/registry)
    """
    candidate_endpoint = os.environ.get("ONLINE_RL_CANDIDATE_ENDPOINT", "")
    if not candidate_endpoint:
        raise ValueError("ONLINE_RL_CANDIDATE_ENDPOINT is required for real eval mode")

    config = EvalConfig(
        suite_id=os.environ.get("ONLINE_RL_EVAL_SUITE", "smoke_v1"),
        model_name=os.environ.get("ONLINE_RL_MODEL", "model-32b"),
        registry_dir=os.environ.get("ONLINE_RL_REGISTRY_DIR", str(DEFAULT_REGISTRY_DIR)),
    )

    return CandidateEvaluator(
        candidate_endpoint=candidate_endpoint,
        baseline_endpoint=os.environ.get("ONLINE_RL_BASELINE_ENDPOINT"),
        config=config,
        api_key=os.environ.get("ONLINE_RL_API_KEY"),
    )


def _run_local_eval(
    suite_id: str,
    model_name: str,
    candidate_version: str,
) -> tuple[EvalRun, EvalRun | None]:
    """Run evaluation in local mode without full inference stack

    In local mode, try these strategies in order:
    1. If ONLINE_RL_CANDIDATE_ENDPOINT is set and reachable, use it (local vLLM)
    2. Otherwise, generate mock results for smoke testing

    This allows `qctl up --local --with-rl` to run eval gate without GPU
    """
    local_endpoint = os.environ.get("ONLINE_RL_CANDIDATE_ENDPOINT", "http://localhost:8000")

    try:
        import httpx

        resp = httpx.get(f"{local_endpoint}/health", timeout=5.0)
        if resp.status_code == 200:
            log.info("local eval: using local vLLM endpoint", extra={"endpoint": local_endpoint})
            config = EvalConfig(suite_id=suite_id, model_name=model_name)
            evaluator = CandidateEvaluator(
                candidate_endpoint=local_endpoint,
                baseline_endpoint=None,
                config=config,
            )
            return evaluator.evaluate_both(candidate_version)
    except Exception:
        pass

    log.info("local eval: no model available, generating mock results")
    return _generate_mock_eval(suite_id, model_name, candidate_version), None


def _generate_mock_eval(suite_id: str, model_name: str, model_version: str) -> EvalRun:
    """Generate mock evaluation results for local testing

    Returns passing results for smoke tests so the RL loop can exercise
    the full pipeline without requiring actual model inference
    """
    from kairo_common.ids import new_eval_run_id

    items = [
        ItemResult(
            item_id=f"mock_{i}",
            passed=i < 8,
            score=0.9 if i < 8 else 0.3,
            latency_ms=100 + i * 10,
            cost_usd=0.001,
            safety_flag=False,
        )
        for i in range(10)
    ]

    return EvalRun(
        eval_run_id=new_eval_run_id(),
        suite=suite_id,
        model=model_name,
        model_version=model_version,
        router_url="local://mock",
        items=items,
    )
