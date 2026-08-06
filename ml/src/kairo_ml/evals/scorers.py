"""Scorers

A scorer turns a model response + expected answer into a pass/fail plus a score.
Coding/tool/browser/SQL scorers run in an isolated scorer after the agent
stops so the agent never sees hidden tests; those live behind the same
`Scorer` protocol and are implemented in the harness layer. The ones here are
the deterministic text scorers used by the smoke suite.
"""

from __future__ import annotations

import re
from typing import Protocol


class Scorer(Protocol):
    def score(self, *, response: str, expected: str) -> tuple[bool, float]: ...


class ExactMatchScorer:
    def score(self, *, response: str, expected: str) -> tuple[bool, float]:
        ok = _normalize(response) == _normalize(expected)
        return ok, 1.0 if ok else 0.0


class ContainsScorer:
    """Passes if the normalized expected answer appears in the response.

    Useful for short factual/math smoke items where the final answer is a token
    or phrase embedded in prose.
    """

    def score(self, *, response: str, expected: str) -> tuple[bool, float]:
        ok = _normalize(expected) in _normalize(response)
        return ok, 1.0 if ok else 0.0


class NumericScorer:
    """Passes if the last number in the response equals the expected number."""

    _NUM = re.compile(r"-?\d+(?:\.\d+)?")

    def score(self, *, response: str, expected: str) -> tuple[bool, float]:
        found = self._NUM.findall(response)
        want = self._NUM.findall(expected)
        if not found or not want:
            return False, 0.0
        ok = abs(float(found[-1]) - float(want[-1])) < 1e-6
        return ok, 1.0 if ok else 0.0


class HiddenTestsScorer:
    """Runs hidden tests in an isolated sandbox via the strict coding harness.

    Unlike other scorers, this one requires the full task context (source files,
    hidden tests) to be passed via the item dict. The `expected` field is ignored;
    scoring is based on test pass rate.
    """

    def __init__(self) -> None:
        self._harness = None

    def _get_harness(self):
        if self._harness is None:
            from kairo_ml.evals.harnesses import HarnessConfig, StrictCodingHarness

            self._harness = StrictCodingHarness(HarnessConfig(network_allowed=False))
        return self._harness

    def score(
        self, *, response: str, expected: str, item: dict | None = None
    ) -> tuple[bool, float]:
        if item is None or "source_files" not in item:
            ok = _normalize(expected) in _normalize(response)
            return ok, 1.0 if ok else 0.0

        from kairo_ml.evals.harnesses import CodingTask

        task = CodingTask(
            task_id=item.get("id", "unknown"),
            prompt=item.get("prompt", ""),
            source_files=item.get("source_files", {}),
            hidden_tests=item.get("hidden_tests", {}),
            answer_secrets=item.get("answer_secrets", []),
        )

        def agent_fn(ctx):
            for path in task.source_files:
                if path.endswith(".py"):
                    ctx.write_file(path, response)
                    break

        result = self._get_harness().evaluate(task, agent_fn)
        return result.passed, result.reward


_SCORERS: dict[str, Scorer] = {
    "exact": ExactMatchScorer(),
    "contains": ContainsScorer(),
    "numeric": NumericScorer(),
    "hidden_tests": HiddenTestsScorer(),
}


def get_scorer(name: str) -> Scorer:
    if name not in _SCORERS:
        raise KeyError(f"unknown scorer: {name}")
    return _SCORERS[name]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())
