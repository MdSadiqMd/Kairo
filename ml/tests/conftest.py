from __future__ import annotations

import pytest
from kairo_ml.sandbox.base import RunResult


class FakeSandbox:
    """In-memory Sandbox implementing the kairo_ml.sandbox.base.Sandbox protocol.

    Deliberately does NOT import LocalSandbox: the runtime depends only on the
    protocol, so tests inject this fake.
    """

    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self._root = "/fake-sandbox"

    @property
    def root(self) -> str:
        return self._root

    def write_file(self, relpath: str, content: str) -> None:
        self._files[relpath] = content

    def read_file(self, relpath: str) -> str:
        if relpath not in self._files:
            raise FileNotFoundError(relpath)
        return self._files[relpath]

    def exists(self, relpath: str) -> bool:
        return relpath in self._files

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: float = 30.0,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        if argv and argv[0] == "cat" and len(argv) > 1 and argv[1] in self._files:
            return RunResult(0, self._files[argv[1]], "", False)
        return RunResult(0, " ".join(argv), "", False)

    def cleanup(self) -> None:
        self._files.clear()


@pytest.fixture
def sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def sandbox_factory() -> type[FakeSandbox]:
    return FakeSandbox
