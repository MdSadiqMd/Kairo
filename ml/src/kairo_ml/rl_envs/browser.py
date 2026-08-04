"""Browser RL environment

A deterministic mock-DOM simulator: elements have text/value/visibility, clicks
fire scripted transitions, and the validator checks DOM/URL assertions. This is
the offline, hermetic stand-in used in CI and RL rollouts. The PRODUCTION
backend for this environment is Playwright driving a real headless browser with
DOM assertions and screenshot diffs; that is out of scope here because
it needs a browser binary and is non-deterministic, but this env implements the
same reset/step/score contract so the two are drop-in interchangeable
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, ClassVar

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

log = get_logger("kairo-ml.rl_envs.browser")


@dataclass(frozen=True)
class BrowserTask:
    task_id: str
    prompt: str
    dom: dict[str, dict[str, Any]]  # element_id -> {"text","value","visible"}
    url: str
    # element_id -> mutations applied on click: {"url": ..., "set": {elem: {attr: val}}}
    transitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    assertions: list[dict[str, Any]] = field(default_factory=list)


_TASKS: dict[str, BrowserTask] = {
    "login_flow": BrowserTask(
        task_id="login_flow",
        prompt="Type 'ada' into #username then click #login. Goal: reach /dashboard.",
        dom={
            "#username": {"text": "", "value": "", "visible": True},
            "#login": {"text": "Log in", "value": "", "visible": True},
            "#banner": {"text": "Please log in", "value": "", "visible": True},
        },
        url="/login",
        transitions={
            "#login": {"url": "/dashboard", "set": {"#banner": {"text": "Welcome"}}},
        },
        assertions=[
            {"url": "/dashboard"},
            {"element": "#banner", "attr": "text", "equals": "Welcome"},
        ],
    ),
}


class BrowserEnv(RLEnvironment):
    name: ClassVar[str] = "browser"

    def __init__(self, *, no_network: bool = True) -> None:
        super().__init__(no_network=no_network)
        self._task: BrowserTask | None = None
        self._dom: dict[str, dict[str, Any]] = {}
        self._url = ""
        self._done = False

    def available_tasks(self) -> list[str]:
        return sorted(_TASKS)

    def reset(self, task_id: str) -> Observation:
        if task_id not in _TASKS:
            raise KeyError(f"unknown browser task: {task_id!r}")
        self._task = _TASKS[task_id]
        self._task_id = task_id
        self._dom = copy.deepcopy(self._task.dom)
        self._url = self._task.url
        self._done = False
        obs = self._observe(self._task.prompt)
        self._transcript.record_observation(obs.text, task_id=task_id)
        return obs

    def _observe(self, text: str) -> Observation:
        assert self._task is not None
        return Observation(
            task_id=self._task.task_id,
            text=text,
            data={"url": self._url, "dom": copy.deepcopy(self._dom)},
        )

    def step(self, action: Action) -> tuple[Observation, Reward, Done, Info]:
        """Drive the mock DOM: click / type / navigate / stop."""
        if self._task is None:
            raise RuntimeError("call reset() before step()")
        kind = action.kind
        self._transcript.record_action(action.content, verb=kind, args=action.args)
        if kind == "click":
            self._apply_transition(str(action.args.get("element", "")))
            text = "clicked"
        elif kind == "type":
            elem = str(action.args.get("element", ""))
            if elem in self._dom:
                self._dom[elem]["value"] = action.args.get("text", "")
            text = "typed"
        elif kind == "navigate":
            self._url = str(action.args.get("url", self._url))
            text = "navigated"
        elif kind in ("stop", "submit"):
            self._done = True
            text = "stopped"
        else:
            raise ValueError(f"unknown action kind: {kind!r}")
        return self._observe(text), Reward(0.0), self._done, {"url": self._url}

    def _apply_transition(self, element: str) -> None:
        assert self._task is not None
        transition = self._task.transitions.get(element)
        if not transition:
            return
        if "url" in transition:
            self._url = str(transition["url"])
        for elem, attrs in transition.get("set", {}).items():
            if elem in self._dom:
                self._dom[elem].update(attrs)

    def score(self) -> ScoreReport:
        if self._task is None:
            raise RuntimeError("call reset() before score()")
        failures = [a for a in self._task.assertions if not self._assert_holds(a)]
        passed = not failures
        report = ScoreReport(
            task_id=self._task.task_id,
            reward=1.0 if passed else 0.0,
            passed=passed,
            details={"url": self._url, "failed_assertions": failures},
        )
        self._transcript.record_score(str(report.reward), passed=passed)
        return report

    def _assert_holds(self, assertion: dict[str, Any]) -> bool:
        if "url" in assertion:
            return self._url == assertion["url"]
        element = assertion.get("element", "")
        attr = assertion.get("attr", "text")
        if element not in self._dom:
            return False
        return self._dom[element].get(attr) == assertion.get("equals")
