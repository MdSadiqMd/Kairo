"""State separation for the agent runtime

An agent's state is not one blob. Five distinct stores are
kept separate on purpose, because conflating them causes real failures:

- conversation state — an append-only event stream of the dialogue. Never
  mutated in place: replaying it must never re-trigger a side effect
- workflow state — the durable execution log driven by the engine in
  workflow.py (Temporal in production). Owns *control flow*, not content
- machine state — a *reference* to a sandbox snapshot, never the sandbox
  bytes inline; the sandbox owns its own filesystem
- artifact state — durable outputs (S3 in production, local here)
- tool logs — an append-only audit trail of every tool/gate decision

Each store below has its own typed interface and its own on-disk location, so a
bug in one plane (e.g. a corrupt tool log) cannot silently corrupt another
(e.g. the conversation the model will replay). StateStores wires them under
one root while keeping the five planes physically distinct
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from kairo_common import get_logger

logger = get_logger(__name__)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")


@dataclass(frozen=True)
class ConversationEvent:
    seq: int
    role: str  # user | assistant | tool | system
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationStore:
    """Append-only conversation event stream (conversation state)

    Append-only is the invariant: the model reconstructs context by reading the
    stream, so an in-place edit would rewrite history under a running agent
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(
        self, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> ConversationEvent:
        event = ConversationEvent(self.count(), role, content, metadata or {})
        _append_jsonl(self._path, asdict(event))
        return event

    def events(self) -> list[ConversationEvent]:
        return [ConversationEvent(**record) for record in _read_jsonl(self._path)]

    def count(self) -> int:
        return len(_read_jsonl(self._path))


class WorkflowEventStore:
    """Durable append-only event log per workflow run (workflow state)

    This is the persistence layer the event-sourced engine in workflow.py
    replays from after a crash. It stores opaque engine events; the engine owns
    their schema. One file per run_id keeps runs isolated
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, run_id: str) -> Path:
        return self._dir / f"{run_id}.jsonl"

    def append(self, run_id: str, event: dict[str, Any]) -> None:
        _append_jsonl(self._path(run_id), event)

    def load(self, run_id: str) -> list[dict[str, Any]]:
        return _read_jsonl(self._path(run_id))

    def exists(self, run_id: str) -> bool:
        return self._path(run_id).exists()


class MachineStateStore:
    """Sandbox snapshot *references* (machine state)

    Deliberately stores a reference/manifest, not raw sandbox contents: the
    sandbox owns its bytes. Restoring re-applies the manifest to a fresh
    sandbox, which is what hibernate/resume needs
    """

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, key: str) -> Path:
        return self._dir / f"{key}.json"

    def save(self, key: str, snapshot: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, default=str), encoding="utf-8")

    def load(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded


class ArtifactStore:
    """Durable artifact outputs (artifact state; S3 in production)"""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def put_text(self, name: str, content: str) -> str:
        path = self._dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def get_text(self, name: str) -> str | None:
        path = self._dir / name
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_names(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(str(p.relative_to(self._dir)) for p in self._dir.rglob("*") if p.is_file())


class ToolLogStore:
    """Append-only tool/gate audit trail (tool logs)"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, entry: dict[str, Any]) -> None:
        _append_jsonl(self._path, entry)

    def entries(self) -> list[dict[str, Any]]:
        return _read_jsonl(self._path)


@dataclass
class StateStores:
    """The five state planes wired under one root but kept physically separate"""

    conversation: ConversationStore
    workflow: WorkflowEventStore
    machine: MachineStateStore
    artifacts: ArtifactStore
    tool_logs: ToolLogStore

    @classmethod
    def local(cls, root: str | Path, run_id: str) -> StateStores:
        base = Path(root)
        return cls(
            conversation=ConversationStore(base / "conversation" / f"{run_id}.jsonl"),
            workflow=WorkflowEventStore(base / "workflow"),
            machine=MachineStateStore(base / "machine"),
            artifacts=ArtifactStore(base / "artifacts"),
            tool_logs=ToolLogStore(base / "tool_logs" / f"{run_id}.jsonl"),
        )
