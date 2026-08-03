"""Sandbox protocol

The contract every isolated-execution consumer codes against. Implementations
provide an ephemeral working directory, file I/O scoped to it, and command
execution with an enforced timeout. Network policy, git-history reinitialization,
and cleanup are implementation concerns documented per implementation
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


@runtime_checkable
class Sandbox(Protocol):
    """An ephemeral, filesystem-scoped execution environment.

    Sandboxes are single-use: create, run a task, score, ``cleanup``. All paths
    are relative to and confined within ``root``.
    """

    @property
    def root(self) -> str: ...

    def write_file(self, relpath: str, content: str) -> None: ...

    def read_file(self, relpath: str) -> str: ...

    def exists(self, relpath: str) -> bool: ...

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: float = 30.0,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult: ...

    def cleanup(self) -> None: ...
