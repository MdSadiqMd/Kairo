"""RL environment contract

`RLEnvironment` is the ABC every verifiable-reward environment implements. The
value types (`Observation`, `Action`, `Reward`, `ScoreReport`) are the
shared vocabulary the agent loop and the scorer speak

Sandbox requirements honored by subclasses: ephemeral filesystem per run,
default-deny network, enforced timeouts, a full transcript + tool-output log,
hidden tests mounted only for the scorer, and guaranteed cleanup after every
run. Environments that need a real filesystem (code repair) open a
`LocalSandbox`; in-memory environments (math, SQL, tool use, browser) keep the
same guarantees on an in-process simulator
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from kairo_ml.rl_envs.transcript import Transcript
from kairo_ml.sandbox.local import LocalSandbox

Done = bool
Info = dict[str, Any]


@dataclass(frozen=True)
class Observation:
    """What the agent sees on ``reset`` and after each ``step``."""

    task_id: str
    text: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """An agent action. ``kind`` names the tool/verb; ``content``/``args`` carry it."""

    kind: str
    content: str = ""
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Reward:
    value: float
    info: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScoreReport:
    """Final verdict produced by the isolated scorer after the agent stops."""

    task_id: str
    reward: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)
    hacking_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "reward": self.reward,
            "passed": self.passed,
            "details": self.details,
            "hacking_flags": self.hacking_flags,
        }


class RLEnvironment(ABC):
    """Base class for verifiable-reward environments.

    Lifecycle: ``reset(task_id)`` → repeated ``step(action)`` → ``score()`` →
    ``cleanup()``. ``cleanup`` is idempotent and always safe to call, including
    from ``__exit__``, so a run never leaks its sandbox.
    """

    name: ClassVar[str] = "base"
    requires_network: ClassVar[bool] = False

    def __init__(self, *, no_network: bool = True) -> None:
        self._transcript = Transcript()
        self._no_network = no_network
        self._sandbox: LocalSandbox | None = None
        self._task_id: str | None = None

    @property
    def transcript(self) -> Transcript:
        return self._transcript

    @property
    def sandbox(self) -> LocalSandbox:
        if self._sandbox is None:
            raise RuntimeError("no sandbox; this environment did not open one on reset()")
        return self._sandbox

    def _open_sandbox(self) -> LocalSandbox:
        """Discard any previous sandbox and open a fresh ephemeral one."""
        if self._sandbox is not None:
            self._sandbox.cleanup()
        self._sandbox = LocalSandbox(no_network=self._no_network)
        return self._sandbox

    @abstractmethod
    def available_tasks(self) -> list[str]: ...

    @abstractmethod
    def reset(self, task_id: str) -> Observation: ...

    @abstractmethod
    def step(self, action: Action) -> tuple[Observation, Reward, Done, Info]: ...

    @abstractmethod
    def score(self) -> ScoreReport: ...

    def cleanup(self) -> None:
        if self._sandbox is not None:
            self._sandbox.cleanup()
            self._sandbox = None

    def __enter__(self) -> RLEnvironment:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.cleanup()
