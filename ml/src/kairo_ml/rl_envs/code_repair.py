"""Code-repair RL environment

The agent is dropped into a sandbox containing buggy source and a task
description. It edits files, may run commands, then stops. Only after it stops
does :meth:`CodeRepairEnv.score` mount the HIDDEN pytest tests into the sandbox,
run them plus a lint/compile pass, and set reward = fraction of hidden tests
passing. The hidden tests are never written where the agent can read them until
scoring, so the agent cannot pass by reading the oracle
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import ClassVar

from kairo_common import get_logger

from kairo_ml.rl_envs.base import (
    Action,
    Done,
    Info,
    Observation,
    Reward,
    RLEnvironment,
    ScoreReport,
)

log = get_logger("kairo-ml.rl_envs.code_repair")

_HIDDEN_DIR = ".hidden_scorer"
_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")
_ERROR_RE = re.compile(r"(\d+) error(?:s)?")


@dataclass(frozen=True)
class CodeRepairTask:
    task_id: str
    prompt: str
    source_files: dict[str, str]  # agent-visible buggy code
    hidden_tests: dict[str, str] = field(default_factory=dict)  # scorer-only


_TASKS: dict[str, CodeRepairTask] = {
    "off_by_one_sum": CodeRepairTask(
        task_id="off_by_one_sum",
        prompt="`sum_to(n)` should return 1+2+...+n. Fix the bug so the hidden tests pass.",
        source_files={
            "solution.py": (
                "def sum_to(n):\n"
                "    total = 0\n"
                "    # BUG: range stops at n instead of n+1\n"
                "    for i in range(1, n):\n"
                "        total += i\n"
                "    return total\n"
            )
        },
        hidden_tests={
            "test_solution.py": (
                "from solution import sum_to\n\n"
                "def test_small():\n"
                "    assert sum_to(1) == 1\n\n"
                "def test_five():\n"
                "    assert sum_to(5) == 15\n\n"
                "def test_ten():\n"
                "    assert sum_to(10) == 55\n"
            )
        },
    ),
}


class CodeRepairEnv(RLEnvironment):
    name: ClassVar[str] = "code_repair"

    def __init__(self, *, no_network: bool = True) -> None:
        super().__init__(no_network=no_network)
        self._task: CodeRepairTask | None = None
        self._stopped = False

    def available_tasks(self) -> list[str]:
        return sorted(_TASKS)

    def reset(self, task_id: str) -> Observation:
        if task_id not in _TASKS:
            raise KeyError(f"unknown code_repair task: {task_id!r}")
        self._task = _TASKS[task_id]
        self._task_id = task_id
        self._stopped = False
        sandbox = self._open_sandbox()
        for relpath, content in self._task.source_files.items():
            sandbox.write_file(relpath, content)
        sandbox.reinit_git()
        obs = Observation(
            task_id=task_id,
            text=self._task.prompt,
            data={"files": sorted(self._task.source_files)},
        )
        self._transcript.record_observation(obs.text, task_id=task_id)
        return obs

    def step(self, action: Action) -> tuple[Observation, Reward, Done, Info]:
        """Handle one agent action.

        ``write_file`` edits a file; ``read_file`` returns its content; ``run``
        executes a command in the sandbox; ``stop``/``submit`` ends the episode.
        Step reward is always 0 — the only reward is the terminal score, so the
        agent cannot farm partial credit before the hidden tests run.
        """
        if self._task is None:
            raise RuntimeError("call reset() before step()")
        sandbox = self.sandbox
        kind = action.kind
        self._transcript.record_action(action.content, verb=kind, args=action.args)
        info: Info = {}
        text = ""
        if kind == "write_file":
            sandbox.write_file(str(action.args["path"]), action.content)
            text = f"wrote {action.args['path']}"
        elif kind == "read_file":
            text = sandbox.read_file(str(action.args["path"]))
            self._transcript.record_tool_output(text, path=action.args["path"])
        elif kind == "run":
            result = sandbox.run(
                action.args.get("argv", []), timeout_s=action.args.get("timeout_s", 30.0)
            )
            text = result.stdout + result.stderr
            info = {"exit_code": result.exit_code, "timed_out": result.timed_out}
            self._transcript.record_tool_output(text, exit_code=result.exit_code)
        elif kind in ("stop", "submit"):
            self._stopped = True
        else:
            raise ValueError(f"unknown action kind: {kind!r}")
        done = self._stopped
        obs = Observation(task_id=self._task.task_id, text=text, data=info)
        return obs, Reward(value=0.0), done, info

    def score(self) -> ScoreReport:
        """Mount hidden tests (scorer-only) and run them + lint after the agent stops."""
        if self._task is None:
            raise RuntimeError("call reset() before score()")
        sandbox = self.sandbox
        # Hidden tests are written only now, once the agent can no longer act.
        for relpath, content in self._task.hidden_tests.items():
            sandbox.write_file(f"{_HIDDEN_DIR}/{relpath}", content)

        lint_ok = self._lint(list(self._task.source_files))
        passed, total = self._run_hidden_tests()
        reward = passed / total if total else 0.0
        report = ScoreReport(
            task_id=self._task.task_id,
            reward=reward,
            passed=total > 0 and passed == total and lint_ok,
            details={"tests_passed": passed, "tests_total": total, "lint_ok": lint_ok},
        )
        self._transcript.record_score(str(reward), passed=report.passed)
        return report

    def _lint(self, source_files: list[str]) -> bool:
        """Compile each source file as a cheap, dependency-free lint gate."""
        argv = [sys.executable, "-m", "py_compile", *source_files]
        result = self.sandbox.run(argv, timeout_s=30.0)
        return result.exit_code == 0

    def _run_hidden_tests(self) -> tuple[int, int]:
        # ``rootdir`` = sandbox root so `from solution import ...` resolves; the
        # hidden tests live under a subdir but pytest adds root to sys.path.
        argv = [
            sys.executable,
            "-m",
            "pytest",
            _HIDDEN_DIR,
            "-p",
            "no:cacheprovider",
            "--rootdir",
            ".",
            "--import-mode=importlib",
            "-q",
            "--no-header",
        ]
        result = self.sandbox.run(argv, timeout_s=120.0, env=self._pytest_env())
        return self._parse_pytest(result.stdout + result.stderr)

    def _pytest_env(self) -> dict[str, str]:
        # Ensure the sandbox root is importable so `import solution` works under
        # importlib import-mode regardless of pytest's rootdir insertion.
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = self.sandbox.root + (os.pathsep + existing if existing else "")
        return env

    @staticmethod
    def _parse_pytest(output: str) -> tuple[int, int]:
        passed = sum(int(m) for m in _PASSED_RE.findall(output))
        failed = sum(int(m) for m in _FAILED_RE.findall(output))
        errors = sum(int(m) for m in _ERROR_RE.findall(output))
        total = passed + failed + errors
        return passed, total
