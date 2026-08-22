from __future__ import annotations

import shutil

import pytest
from kairo_ml.evals.harnesses import (
    AgentContext,
    CodingTask,
    HarnessConfig,
    StrictCodingHarness,
    evaluate,
)

_BUGGY = "def add(a, b):\n    return a - b  # bug\n"
_FIXED = "def add(a, b):\n    return a + b\n"
_TESTS = (
    "from solution import add\n\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n\n"
    "def test_add_zero():\n"
    "    assert add(0, 0) == 0\n"
)

TASK = CodingTask(
    task_id="add_fix",
    prompt="Fix add() so it returns a + b.",
    source_files={"solution.py": _BUGGY},
    hidden_tests={"test_solution.py": _TESTS},
    answer_secrets=["return a + b"],
)


def _fixer(ctx: AgentContext) -> None:
    ctx.write_file("solution.py", _FIXED)


def _noop(ctx: AgentContext) -> None:
    return None


def test_reinitializes_git_and_denies_network() -> None:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    result = evaluate(TASK, _fixer)
    assert result.git_reinitialized
    assert result.network_denied


def test_correct_agent_passes_isolated_scoring() -> None:
    result = evaluate(TASK, _fixer)
    assert result.tests_total == 2
    assert result.tests_passed == 2
    assert result.lint_ok
    # _fixer wrote "return a + b", which is the answer secret -> retrieval flag.
    assert result.answer_retrieval_detected
    assert result.flagged_entries


def test_wrong_agent_fails() -> None:
    result = evaluate(TASK, _noop)
    assert not result.passed
    assert result.tests_passed < result.tests_total


def test_scoring_happens_after_agent_stops() -> None:
    seen: dict[str, bool] = {}

    def agent(ctx: AgentContext) -> None:
        # Hidden test must be invisible while the agent is running.
        seen["hidden_visible_during_run"] = ".hidden_scorer/test_solution.py" in ctx.list_files()
        ctx.write_file("solution.py", _FIXED)

    result = evaluate(TASK, agent)
    assert seen["hidden_visible_during_run"] is False
    assert result.tests_passed == 2


def test_package_install_allowlist_refuses_unlisted() -> None:
    captured: dict[str, int] = {}

    def agent(ctx: AgentContext) -> None:
        blocked = ctx.run(["pip", "install", "requests"])
        captured["blocked_code"] = blocked.exit_code
        assert "allowlist" in blocked.stderr
        ctx.write_file("solution.py", _FIXED)

    cfg = HarnessConfig(allowed_packages=frozenset({"pytest"}))
    result = evaluate(TASK, agent, config=cfg)
    assert captured["blocked_code"] == 1
    assert result.tests_passed == 2


def test_no_retrieval_when_agent_reasons_independently() -> None:
    # Agent writes an equivalent fix that does not echo the oracle string.
    def agent(ctx: AgentContext) -> None:
        ctx.write_file("solution.py", "def add(a, b):\n    return sum((a, b))\n")

    result = evaluate(TASK, agent)
    assert result.tests_passed == 2
    assert not result.answer_retrieval_detected
    assert result.passed


def test_strict_coding_harness_wrapper() -> None:
    harness = StrictCodingHarness(HarnessConfig())
    result = harness.evaluate(TASK, _fixer)
    assert result.tests_total == 2
