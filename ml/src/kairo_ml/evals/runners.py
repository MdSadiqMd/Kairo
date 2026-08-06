"""Eval runners

A runner executes a suite against a served model and returns an `EvalRun`. The
`SmokeRunner` drives the real router over its OpenAI-compatible API — the same
path production traffic takes — so the smoke suite measures the deployed system,
not a mock. A pluggable `Responder` lets tests exercise scoring logic without
a live server

The smoke suite is deliberately small (<5 min, ~50 items): it runs on
every deploy and every online-RL cycle, and is the prerequisite for the
per-cycle eval gate the real-time RL loop needs

Local Mode (MiniStack): `LocalRunner` supports running evals against a local
vLLM instance (typically localhost:8000) without requiring the full AWS inference
stack. Enable via KAIRO_ENV=local or by passing a localhost URL. Falls back to
mock responses for smoke tests when no local model is available
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import httpx
from kairo_common import get_logger

from kairo_ml.evals.models import EvalRun, EvalSpec, ItemResult
from kairo_ml.evals.scorers import get_scorer

log = get_logger("kairo-ml.evals.runners")

# A Responder maps a list of chat messages to (response_text, cost_usd). The
# default hits the router; tests inject a deterministic function.
Responder = Callable[[list[dict]], tuple[str, float]]


class DatasetItem(Protocol):
    id: str


def is_local_mode() -> bool:
    """Detect if running in local mode (MiniStack).

    Local mode is enabled when:
    - KAIRO_ENV=local
    - KAIRO_LOCAL=1 or true
    """
    kairo_env = os.environ.get("KAIRO_ENV", "").lower()
    kairo_local = os.environ.get("KAIRO_LOCAL", "").lower()
    return kairo_env == "local" or kairo_local in ("1", "true")


def is_local_url(url: str | None) -> bool:
    """Check if URL points to localhost."""
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def resolve_dataset_uri(uri: str) -> str:
    """Resolve environment variable placeholders in dataset URIs.

    Supports ``${VAR}`` and ``$VAR`` syntax. Common placeholders:
    - DATASETS_BUCKET: S3 bucket for eval datasets (env-specific)
    - KAIRO_ENV: Environment name (local, dev, staging, prod)

    Default bucket pattern: kairo-cloud-{env}-datasets
    """
    import re

    def _replace(match: re.Match) -> str:
        var = match.group(1) or match.group(2)
        default = _get_bucket_default(var)
        return os.environ.get(var, default)

    return re.sub(r"\$\{(\w+)\}|\$(\w+)", _replace, uri)


def _get_bucket_default(var: str) -> str:
    """Get default value for common bucket variables based on KAIRO_ENV."""
    env = os.environ.get("KAIRO_ENV", "dev")
    bucket_defaults = {
        "DATASETS_BUCKET": f"kairo-cloud-{env}-datasets",
        "CHECKPOINTS_BUCKET": f"kairo-cloud-{env}-checkpoints",
        "EVAL_RESULTS_BUCKET": f"kairo-cloud-{env}-eval-results",
        "MODEL_ARTIFACTS_BUCKET": f"kairo-cloud-{env}-model-artifacts",
    }
    return bucket_defaults.get(var, "")


def load_jsonl_dataset(uri: str) -> list[dict]:
    """Load a JSONL dataset from S3 or local filesystem

    Supports `s3://`, `file://`, or bare filesystem paths
    Environment variables in the URI are expanded (e.g., ``s3://${DATASETS_BUCKET}/...``)
    """
    resolved = resolve_dataset_uri(uri)
    if resolved.startswith("s3://"):
        from kairo_ml.training.loaders import load_from_s3

        return load_from_s3(resolved)
    path = resolved.removeprefix("file://")
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


class SmokeRunner:
    def __init__(self, responder: Responder) -> None:
        self._respond = responder

    @classmethod
    def for_router(
        cls, router_url: str, model: str, *, api_key: str | None = None, timeout_s: float = 60.0
    ) -> SmokeRunner:
        client = httpx.Client(timeout=timeout_s)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        def respond(messages: list[dict]) -> tuple[str, float]:
            resp = client.post(
                f"{router_url.rstrip('/')}/v1/chat/completions",
                json={"model": model, "messages": messages},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            # Rough cost proxy from tokens; the real $/token comes from cost tracking.
            cost = usage.get("total_tokens", 0) * 1e-6
            return text, cost

        return cls(respond)

    def run(
        self, spec: EvalSpec, *, model: str, model_version: str, router_url: str | None
    ) -> EvalRun:
        items = load_jsonl_dataset(spec.dataset_uri)
        results: list[ItemResult] = []
        for item in items:
            scorer = get_scorer(item.get("scorer", spec.scorer))
            messages = item.get("messages") or [{"role": "user", "content": item["prompt"]}]
            started = time.monotonic()
            response, cost = self._respond(messages)
            latency_ms = int((time.monotonic() - started) * 1000)
            passed, score = scorer.score(response=response, expected=item.get("expected", ""))
            results.append(
                ItemResult(
                    item_id=str(item["id"]),
                    passed=passed,
                    score=score,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    safety_flag=bool(item.get("safety_flag_expected", False)) and not passed,
                )
            )
        return EvalRun(
            eval_run_id=f"eval_{uuid.uuid4().hex[:12]}",
            suite=spec.id,
            model=model,
            model_version=model_version,
            router_url=router_url,
            items=results,
        )


class LocalRunner:
    """Runner for local development (MiniStack) without AWS dependencies.

    Supports three modes:
    1. Real local vLLM: Connects to a local vLLM instance (e.g., localhost:8000)
    2. Mock mode: Returns deterministic responses for smoke tests
    3. Hybrid: Falls back to mock if local vLLM is unavailable

    Use LocalRunner.for_local() to auto-detect the best mode
    """

    DEFAULT_VLLM_URL = "http://localhost:8000"

    def __init__(self, responder: Responder, *, mode: str = "auto") -> None:
        self._respond = responder
        self._mode = mode

    @classmethod
    def for_local(
        cls,
        model: str,
        *,
        vllm_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 60.0,
        fallback_to_mock: bool = True,
    ) -> LocalRunner:
        """Create a LocalRunner, auto-detecting vLLM availability

        Args:
            model: Model name to use for inference
            vllm_url: URL of local vLLM instance (default: localhost:8000)
            api_key: Optional API key for vLLM
            timeout_s: Request timeout in seconds
            fallback_to_mock: If True, fall back to mock responses when vLLM unavailable
        """
        url = vllm_url or os.environ.get("LOCAL_VLLM_URL", cls.DEFAULT_VLLM_URL)

        vllm_available = cls._check_vllm_health(url, timeout_s=5.0)

        if vllm_available:
            log.info("local vLLM available", extra={"url": url, "model": model})
            return cls._for_vllm(url, model, api_key=api_key, timeout_s=timeout_s)
        elif fallback_to_mock:
            log.warning("local vLLM unavailable, using mock responder", extra={"url": url})
            return cls._for_mock()
        else:
            raise ConnectionError(f"Local vLLM not available at {url} and fallback_to_mock=False")

    @classmethod
    def _check_vllm_health(cls, url: str, *, timeout_s: float = 5.0) -> bool:
        """Check if local vLLM is healthy."""
        try:
            client = httpx.Client(timeout=timeout_s)
            resp = client.get(f"{url.rstrip('/')}/health")
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
            return False

    @classmethod
    def _for_vllm(
        cls, url: str, model: str, *, api_key: str | None = None, timeout_s: float = 60.0
    ) -> LocalRunner:
        """Create a LocalRunner connected to a real vLLM instance."""
        client = httpx.Client(timeout=timeout_s)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        def respond(messages: list[dict]) -> tuple[str, float]:
            resp = client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json={"model": model, "messages": messages},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            cost = usage.get("total_tokens", 0) * 1e-6
            return text, cost

        return cls(respond, mode="vllm")

    @classmethod
    def _for_mock(cls) -> LocalRunner:
        """Create a LocalRunner with mock responses for smoke tests."""
        return cls(mock_responder, mode="mock")

    def run(
        self, spec: EvalSpec, *, model: str, model_version: str, router_url: str | None
    ) -> EvalRun:
        items = load_jsonl_dataset(spec.dataset_uri)
        results: list[ItemResult] = []
        for item in items:
            scorer = get_scorer(item.get("scorer", spec.scorer))
            messages = item.get("messages") or [{"role": "user", "content": item["prompt"]}]
            started = time.monotonic()
            response, cost = self._respond(messages)
            latency_ms = int((time.monotonic() - started) * 1000)
            passed, score = scorer.score(response=response, expected=item.get("expected", ""))
            results.append(
                ItemResult(
                    item_id=str(item["id"]),
                    passed=passed,
                    score=score,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    safety_flag=bool(item.get("safety_flag_expected", False)) and not passed,
                )
            )
        return EvalRun(
            eval_run_id=f"eval_{uuid.uuid4().hex[:12]}",
            suite=spec.id,
            model=model,
            model_version=model_version,
            router_url=router_url or f"local:{self._mode}",
            items=results,
        )


def mock_responder(messages: list[dict]) -> tuple[str, float]:
    """Mock responder for smoke tests without a real model.

    Uses simple heuristics to generate plausible responses based on the prompt.
    This is NOT meant for accuracy testing — only for verifying the eval pipeline works.
    """
    if not messages:
        return "I don't have enough information to respond.", 0.0

    last_msg = messages[-1].get("content", "").lower()

    mock_responses = {
        "capital": "Paris",
        "france": "Paris",
        "2+2": "4",
        "hello": "Hello! How can I help you?",
        "hi": "Hi there!",
        "code": "```python\nprint('Hello, World!')\n```",
        "fix": "Here's the fixed code:\n```python\ndef solution():\n    return True\n```",
        "error": "The error is in line 5. Here's the fix: ...",
        "bug": "I found the bug. The issue is ...",
    }

    for keyword, response in mock_responses.items():
        if keyword in last_msg:
            return response, 0.001

    return "I understand. Let me help you with that.", 0.001


class CodeRepairRunner:
    """Runner for code repair tasks using the strict coding harness.

    Each item must contain source_files, hidden_tests, and optionally answer_secrets.
    The model is asked to fix the code, and the harness scores it against hidden tests.
    """

    def __init__(self, responder: Responder) -> None:
        self._respond = responder
        self._harness = None

    def _get_harness(self):
        if self._harness is None:
            from kairo_ml.evals.harnesses import HarnessConfig, StrictCodingHarness

            self._harness = StrictCodingHarness(HarnessConfig(network_allowed=False))
        return self._harness

    @classmethod
    def for_router(
        cls, router_url: str, model: str, *, api_key: str | None = None, timeout_s: float = 120.0
    ) -> CodeRepairRunner:
        client = httpx.Client(timeout=timeout_s)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        def respond(messages: list[dict]) -> tuple[str, float]:
            resp = client.post(
                f"{router_url.rstrip('/')}/v1/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 4096},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            cost = usage.get("total_tokens", 0) * 1e-6
            return text, cost

        return cls(respond)

    def run(
        self, spec: EvalSpec, *, model: str, model_version: str, router_url: str | None
    ) -> EvalRun:
        from kairo_ml.evals.harnesses import CodingTask

        items = load_jsonl_dataset(spec.dataset_uri)
        results: list[ItemResult] = []

        for item in items:
            task = CodingTask(
                task_id=str(item["id"]),
                prompt=item["prompt"],
                source_files=item.get("source_files", {}),
                hidden_tests=item.get("hidden_tests", {}),
                answer_secrets=item.get("answer_secrets", []),
            )

            messages = [{"role": "user", "content": task.prompt}]
            for path, content in task.source_files.items():
                messages[0]["content"] += f"\n\n```{path}\n{content}\n```"

            started = time.monotonic()
            response, cost = self._respond(messages)
            latency_ms = int((time.monotonic() - started) * 1000)

            def agent_fn(ctx, resp=response, task=task):
                code = _extract_code_block(resp)
                for path in task.source_files:
                    if path.endswith(".py"):
                        ctx.write_file(path, code)
                        break

            harness_result = self._get_harness().evaluate(task, agent_fn)
            results.append(
                ItemResult(
                    item_id=str(item["id"]),
                    passed=harness_result.passed,
                    score=harness_result.reward,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    safety_flag=harness_result.answer_retrieval_detected,
                )
            )

        return EvalRun(
            eval_run_id=f"eval_{uuid.uuid4().hex[:12]}",
            suite=spec.id,
            model=model,
            model_version=model_version,
            router_url=router_url,
            items=results,
        )


def _extract_code_block(text: str) -> str:
    """Extract Python code from markdown code blocks."""
    import re

    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


class LocalCodeRepairRunner:
    """Local runner for code repair tasks without AWS dependencies.

    Similar to CodeRepairRunner but supports local vLLM or mock fallback.
    """

    def __init__(self, responder: Responder, *, mode: str = "auto") -> None:
        self._respond = responder
        self._mode = mode
        self._harness = None

    def _get_harness(self):
        if self._harness is None:
            from kairo_ml.evals.harnesses import HarnessConfig, StrictCodingHarness

            self._harness = StrictCodingHarness(HarnessConfig(network_allowed=False))
        return self._harness

    @classmethod
    def for_local(
        cls,
        model: str,
        *,
        vllm_url: str | None = None,
        api_key: str | None = None,
        timeout_s: float = 120.0,
        fallback_to_mock: bool = True,
    ) -> LocalCodeRepairRunner:
        """Create a LocalCodeRepairRunner, auto-detecting vLLM availability."""
        url = vllm_url or os.environ.get("LOCAL_VLLM_URL", LocalRunner.DEFAULT_VLLM_URL)

        vllm_available = LocalRunner._check_vllm_health(url, timeout_s=5.0)

        if vllm_available:
            log.info("local vLLM available for code_repair", extra={"url": url, "model": model})
            return cls._for_vllm(url, model, api_key=api_key, timeout_s=timeout_s)
        elif fallback_to_mock:
            log.warning("local vLLM unavailable for code_repair, using mock responder")
            return cls._for_mock()
        else:
            raise ConnectionError(f"Local vLLM not available at {url} and fallback_to_mock=False")

    @classmethod
    def _for_vllm(
        cls, url: str, model: str, *, api_key: str | None = None, timeout_s: float = 120.0
    ) -> LocalCodeRepairRunner:
        """Create a LocalCodeRepairRunner connected to a real vLLM instance."""
        client = httpx.Client(timeout=timeout_s)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

        def respond(messages: list[dict]) -> tuple[str, float]:
            resp = client.post(
                f"{url.rstrip('/')}/v1/chat/completions",
                json={"model": model, "messages": messages, "max_tokens": 4096},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            cost = usage.get("total_tokens", 0) * 1e-6
            return text, cost

        return cls(respond, mode="vllm")

    @classmethod
    def _for_mock(cls) -> LocalCodeRepairRunner:
        """Create a LocalCodeRepairRunner with mock responses for smoke tests."""
        return cls(mock_code_repair_responder, mode="mock")

    def run(
        self, spec: EvalSpec, *, model: str, model_version: str, router_url: str | None
    ) -> EvalRun:
        from kairo_ml.evals.harnesses import CodingTask

        items = load_jsonl_dataset(spec.dataset_uri)
        results: list[ItemResult] = []

        for item in items:
            task = CodingTask(
                task_id=str(item["id"]),
                prompt=item["prompt"],
                source_files=item.get("source_files", {}),
                hidden_tests=item.get("hidden_tests", {}),
                answer_secrets=item.get("answer_secrets", []),
            )

            messages = [{"role": "user", "content": task.prompt}]
            for path, content in task.source_files.items():
                messages[0]["content"] += f"\n\n```{path}\n{content}\n```"

            started = time.monotonic()
            response, cost = self._respond(messages)
            latency_ms = int((time.monotonic() - started) * 1000)

            def agent_fn(ctx, resp=response, task=task):
                code = _extract_code_block(resp)
                for path in task.source_files:
                    if path.endswith(".py"):
                        ctx.write_file(path, code)
                        break

            harness_result = self._get_harness().evaluate(task, agent_fn)
            results.append(
                ItemResult(
                    item_id=str(item["id"]),
                    passed=harness_result.passed,
                    score=harness_result.reward,
                    latency_ms=latency_ms,
                    cost_usd=cost,
                    safety_flag=harness_result.answer_retrieval_detected,
                )
            )

        return EvalRun(
            eval_run_id=f"eval_{uuid.uuid4().hex[:12]}",
            suite=spec.id,
            model=model,
            model_version=model_version,
            router_url=router_url or f"local:{self._mode}",
            items=results,
        )


def mock_code_repair_responder(messages: list[dict]) -> tuple[str, float]:
    """Mock responder for code repair tasks.

    Returns minimal code that attempts to fix common patterns.
    This is NOT meant for accuracy testing — only for verifying the pipeline works.
    """
    if not messages:
        return "```python\npass\n```", 0.001

    last_msg = messages[-1].get("content", "")

    # Extract any existing code blocks for context
    import re

    code_blocks = re.findall(r"```(?:python)?\n(.*?)```", last_msg, re.DOTALL)

    if code_blocks:
        original_code = code_blocks[0]
        # Simple "fixes": replace common error patterns
        fixed = original_code
        fixed = fixed.replace("retrun", "return")
        fixed = fixed.replace("pritn", "print")
        fixed = fixed.replace("deffunction", "def function")
        # If there's a syntax error hint, try to fix it
        if "missing" in last_msg.lower() and "return" in last_msg.lower():
            if "return" not in fixed:
                fixed = fixed.rstrip() + "\n    return None\n"
        return f"```python\n{fixed}\n```", 0.001

    return "```python\ndef solution():\n    return True\n```", 0.001


def get_runner_for_env(
    spec: EvalSpec,
    router_url: str,
    model: str,
    api_key: str | None,
    *,
    force_local: bool = False,
) -> SmokeRunner | CodeRepairRunner | LocalRunner | LocalCodeRepairRunner:
    """Select the appropriate runner based on environment and spec.

    Args:
        spec: The eval specification
        router_url: URL of the inference endpoint
        model: Model name
        api_key: Optional API key
        force_local: Force local mode even without env vars

    Returns:
        Appropriate runner instance
    """
    use_local = force_local or is_local_mode() or is_local_url(router_url)
    runner_type = getattr(spec, "runner", "smoke")

    if use_local:
        vllm_url = router_url if is_local_url(router_url) else None
        if runner_type == "code_repair":
            return LocalCodeRepairRunner.for_local(
                model, vllm_url=vllm_url, api_key=api_key, fallback_to_mock=True
            )
        return LocalRunner.for_local(
            model, vllm_url=vllm_url, api_key=api_key, fallback_to_mock=True
        )
    else:
        if runner_type == "code_repair":
            return CodeRepairRunner.for_router(router_url, model, api_key=api_key)
        return SmokeRunner.for_router(router_url, model, api_key=api_key)
