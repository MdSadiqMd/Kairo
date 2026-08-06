"""Strict coding harness

Runs a coding-eval task against an agent under the controls that stop inflated
scores on evals built from public repos:

- Git history removed + reinitialized to a single commit, so the fix can't
  be recovered from commit history.
- Network deny-by-default via the sandbox; opt-in only
- Package-registry allowlist: install commands are checked against a config
  allowlist and refused otherwise (no fetching the answer as a dependency)
- Hidden tests invisible to the agent: they are mounted only for the scorer,
  after the agent has stopped
- Transcript audit: the full action/tool-output log is scanned for retrieval
  of the oracle (answer secrets) — evidence the agent looked the answer up
- Isolated scoring pass: tests + lint run only after `agent_fn` returns

`evaluate(task, agent_fn)` returns a `HarnessResult`
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from kairo_common import get_logger

from kairo_ml.rl_envs.transcript import Transcript
from kairo_ml.sandbox.base import RunResult
from kairo_ml.sandbox.local import LocalSandbox

log = get_logger("kairo-ml.evals.harness")

_HIDDEN_DIR = ".hidden_scorer"
_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")
_ERROR_RE = re.compile(r"(\d+) error(?:s)?")
_INSTALL_RE = re.compile(r"\b(pip|pip3|uv)\b")


@dataclass(frozen=True)
class CodingTask:
    task_id: str
    prompt: str
    source_files: dict[str, str]  # agent-visible buggy code
    hidden_tests: dict[str, str]  # scorer-only pytest files
    answer_secrets: list[str] = field(default_factory=list)  # retrieval canaries


@dataclass(frozen=True)
class HarnessConfig:
    allowed_packages: frozenset[str] = frozenset()
    network_allowed: bool = False
    timeout_s: float = 120.0


@dataclass(frozen=True)
class HarnessResult:
    task_id: str
    passed: bool
    reward: float
    tests_passed: int
    tests_total: int
    lint_ok: bool
    git_reinitialized: bool
    network_denied: bool
    answer_retrieval_detected: bool
    flagged_entries: list[int]
    transcript_jsonl: str

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "reward": self.reward,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "lint_ok": self.lint_ok,
            "git_reinitialized": self.git_reinitialized,
            "network_denied": self.network_denied,
            "answer_retrieval_detected": self.answer_retrieval_detected,
            "flagged_entries": self.flagged_entries,
        }


class AgentContext:
    """The restricted interface the agent gets. Every call is transcript-logged.

    File access is confined to the sandbox; ``run`` denies non-allowlisted
    package installs and inherits the sandbox's network policy.
    """

    def __init__(
        self, sandbox: LocalSandbox, transcript: Transcript, config: HarnessConfig
    ) -> None:
        self._sandbox = sandbox
        self._transcript = transcript
        self._config = config

    def read_file(self, relpath: str) -> str:
        content = self._sandbox.read_file(relpath)
        self._transcript.record_action(f"read_file {relpath}", verb="read_file")
        self._transcript.record_tool_output(content, path=relpath)
        return content

    def write_file(self, relpath: str, content: str) -> None:
        self._sandbox.write_file(relpath, content)
        self._transcript.record_action(content, verb="write_file", path=relpath)

    def list_files(self) -> list[str]:
        root = self._sandbox.root
        found: list[str] = []
        for base, _dirs, files in os.walk(root):
            for name in files:
                rel = os.path.relpath(os.path.join(base, name), root)
                if not rel.startswith((".git" + os.sep, _HIDDEN_DIR + os.sep)):
                    found.append(rel)
        return sorted(found)

    def run(self, argv: list[str], *, timeout_s: float = 30.0) -> RunResult:
        self._transcript.record_action(" ".join(argv), verb="run")
        denied = self._install_denied(argv)
        if denied is not None:
            self._transcript.record_tool_output(denied, denied=True)
            return RunResult(exit_code=1, stdout="", stderr=denied, timed_out=False)
        result = self._sandbox.run(argv, timeout_s=timeout_s)
        self._transcript.record_tool_output(
            result.stdout + result.stderr, exit_code=result.exit_code
        )
        return result

    def _install_denied(self, argv: list[str]) -> str | None:
        """Refuse package installs of anything outside the allowlist."""
        if not argv or "install" not in argv:
            return None
        if not any(_INSTALL_RE.search(part) for part in argv):
            return None
        idx = argv.index("install")
        requested = [a for a in argv[idx + 1 :] if not a.startswith("-")]
        blocked = [pkg for pkg in requested if _norm_pkg(pkg) not in self._config.allowed_packages]
        if blocked:
            return f"registry allowlist: refused install of {blocked}"
        return None


def _norm_pkg(spec: str) -> str:
    return re.split(r"[<>=!~\[]", spec, maxsplit=1)[0].strip().lower()


def _parse_pytest(output: str) -> tuple[int, int]:
    passed = sum(int(m) for m in _PASSED_RE.findall(output))
    failed = sum(int(m) for m in _FAILED_RE.findall(output))
    errors = sum(int(m) for m in _ERROR_RE.findall(output))
    return passed, passed + failed + errors


def evaluate(
    task: CodingTask,
    agent_fn: Callable[[AgentContext], None],
    *,
    config: HarnessConfig | None = None,
) -> HarnessResult:
    cfg = config or HarnessConfig()
    transcript = Transcript()
    sandbox = LocalSandbox(no_network=not cfg.network_allowed)
    try:
        for relpath, content in task.source_files.items():
            sandbox.write_file(relpath, content)
        git_reinitialized = sandbox.reinit_git()
        transcript.record_observation(task.prompt, task_id=task.task_id)

        ctx = AgentContext(sandbox, transcript, cfg)
        agent_fn(ctx)  # the agent acts; hidden tests are NOT on disk yet

        tests_passed, tests_total, lint_ok = _score(sandbox, task)
        # Audit only actions the agent took (audit_answer_leak ignores our own
        # observations), so a hit means the agent surfaced the oracle itself.
        leaks = transcript.audit_answer_leak(task.answer_secrets)
        retrieval = bool(leaks)

        reward = tests_passed / tests_total if tests_total else 0.0
        passed = tests_total > 0 and tests_passed == tests_total and lint_ok and not retrieval
        return HarnessResult(
            task_id=task.task_id,
            passed=passed,
            reward=reward,
            tests_passed=tests_passed,
            tests_total=tests_total,
            lint_ok=lint_ok,
            git_reinitialized=git_reinitialized,
            network_denied=not cfg.network_allowed,
            answer_retrieval_detected=retrieval,
            flagged_entries=[e.seq for e in leaks],
            transcript_jsonl=transcript.to_jsonl(),
        )
    finally:
        sandbox.cleanup()


def _score(sandbox: LocalSandbox, task: CodingTask) -> tuple[int, int, bool]:
    """Isolated scoring pass: mount hidden tests, run tests + lint."""
    for relpath, content in task.hidden_tests.items():
        sandbox.write_file(f"{_HIDDEN_DIR}/{relpath}", content)

    lint = sandbox.run([sys.executable, "-m", "py_compile", *task.source_files], timeout_s=30.0)
    lint_ok = lint.exit_code == 0

    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = sandbox.root + (os.pathsep + existing if existing else "")
    argv = [
        sys.executable,
        "-m",
        "pytest",
        _HIDDEN_DIR,
        "-p",
        "no:cacheprovider",
        "--import-mode=importlib",
        "-q",
        "--no-header",
    ]
    result = sandbox.run(argv, timeout_s=120.0, env=env)
    passed, total = _parse_pytest(result.stdout + result.stderr)
    return passed, total, lint_ok


class StrictCodingHarness:
    """Object wrapper over :func:`evaluate` carrying a fixed :class:`HarnessConfig`."""

    def __init__(self, config: HarnessConfig | None = None) -> None:
        self.config = config or HarnessConfig()

    def evaluate(self, task: CodingTask, agent_fn: Callable[[AgentContext], None]) -> HarnessResult:
        return evaluate(task, agent_fn, config=self.config)
