"""Math RL environment

Validator: exact answer *and* symbolic equivalence via sympy — so `1/2` and
`0.5` score equal, and `x+x` and `2*x` score equal, while genuinely wrong
answers are rejected. Reward is binary (1.0 / 0.0). Parsing is done through
`parse_expr` with the default (safe) transformations and an empty local
namespace so a submitted "answer" cannot execute arbitrary Python
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sympy
from kairo_common import get_logger
from sympy.parsing.sympy_parser import parse_expr

from kairo_ml.rl_envs.base import (
    Action,
    Done,
    Info,
    Observation,
    Reward,
    RLEnvironment,
    ScoreReport,
)

log = get_logger("kairo-ml.rl_envs.math")


@dataclass(frozen=True)
class MathTask:
    task_id: str
    prompt: str
    answer: str


_TASKS: dict[str, MathTask] = {
    "sum_halves": MathTask("sum_halves", "Compute 1/4 + 1/4.", "1/2"),
    "expand_double": MathTask("expand_double", "Simplify x + x.", "2*x"),
    "quadratic_roots_sum": MathTask("quadratic_roots_sum", "Sum of roots of x**2 - 5*x + 6.", "5"),
    "derivative_poly": MathTask(
        "derivative_poly", "Differentiate x**3 with respect to x.", "3*x**2"
    ),
}


def _safe_parse(expr: str) -> sympy.Expr | None:
    try:
        return parse_expr(expr, local_dict={}, evaluate=True)
    except (SyntaxError, TypeError, ValueError, AttributeError, sympy.SympifyError):
        return None


def equivalent(submitted: str, expected: str) -> bool:
    """True when two expressions are mathematically equal.

    ``simplify(a - b) == 0`` catches symbolic equivalence (``x+x`` vs ``2*x``);
    a numeric fallback catches float/rational forms (``0.5`` vs ``1/2``) where
    ``simplify`` returns a tiny non-symbolic residue instead of exact zero.
    """
    a = _safe_parse(submitted)
    b = _safe_parse(expected)
    if a is None or b is None:
        return False
    diff = sympy.simplify(a - b)
    if diff == 0:
        return True
    try:
        return abs(float(diff)) < 1e-9
    except (TypeError, ValueError):
        return False


class MathEnv(RLEnvironment):
    name: ClassVar[str] = "math"

    def __init__(self, *, no_network: bool = True) -> None:
        super().__init__(no_network=no_network)
        self._task: MathTask | None = None
        self._submitted: str | None = None

    def available_tasks(self) -> list[str]:
        return sorted(_TASKS)

    def reset(self, task_id: str) -> Observation:
        if task_id not in _TASKS:
            raise KeyError(f"unknown math task: {task_id!r}")
        self._task = _TASKS[task_id]
        self._task_id = task_id
        self._submitted = None
        obs = Observation(task_id=task_id, text=self._task.prompt)
        self._transcript.record_observation(obs.text, task_id=task_id)
        return obs

    def step(self, action: Action) -> tuple[Observation, Reward, Done, Info]:
        if self._task is None:
            raise RuntimeError("call reset() before step()")
        self._submitted = action.content.strip()
        self._transcript.record_action(self._submitted, verb=action.kind)
        correct = equivalent(self._submitted, self._task.answer)
        reward = Reward(value=1.0 if correct else 0.0)
        obs = Observation(
            task_id=self._task.task_id, text="submitted", data={"answer": self._submitted}
        )
        return obs, reward, True, {"correct": correct}

    def score(self) -> ScoreReport:
        if self._task is None:
            raise RuntimeError("call reset() before score()")
        submitted = self._submitted or ""
        correct = equivalent(submitted, self._task.answer)
        report = ScoreReport(
            task_id=self._task.task_id,
            reward=1.0 if correct else 0.0,
            passed=correct,
            details={"submitted": submitted, "expected": self._task.answer},
        )
        self._transcript.record_score(str(report.reward), passed=correct)
        return report
