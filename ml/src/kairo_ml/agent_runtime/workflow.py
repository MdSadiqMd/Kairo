"""Durable, event-sourced workflow engine

This is the local, testable equivalent of Temporal-on-EKS (the production
backend). Durable execution works by event sourcing*: every side-effecting step
("activity") appends its result to an append-only og the instant it completes.
The workflow body is a plain deterministic function of a WorkflowContext

Replay is the mechanism that makes it crash-safe. To resume, we re-run the same
workflow function from the top; but each ctx.execute(...) call is matched by
call-index against the persisted log:

- if a result was already recorded for that index, we return the recorded
  value and skip the effect entirely — the side effect already happened
  durably, so re-running it would double-execute
- otherwise the effect runs for real and its result is appended

So after a crash, resuming re-drives control flow deterministically, replays the
recorded effects for free, and continues past the crash point exactly once. This
demands the workflow body be deterministic between activities (branching only
on values obtained from ctx.execute), which is the same contract Temporal
imposes on workflow code
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from kairo_common import get_logger

from kairo_ml.agent_runtime.state import WorkflowEventStore

logger = get_logger(__name__)

WorkflowFn = Callable[["WorkflowContext"], Any]

_ACTIVITY_COMPLETED = "activity_completed"
_WORKFLOW_COMPLETED = "workflow_completed"


class WorkflowContext:
    """Handle passed to a workflow body. execute is the only way to run a
    side effect so the engine can record and replay it deterministically"""

    def __init__(self, run_id: str, store: WorkflowEventStore, recorded: dict[int, Any]) -> None:
        self._run_id = run_id
        self._store = store
        self._recorded = recorded
        self._index = 0

    def execute(self, name: str, effect: Callable[[], Any]) -> Any:
        """Run effect once-and-only-once across crashes/replays

        On replay the recorded result is returned without invoking effect,
        which is what prevents double-executed side effects after a resume
        """
        index = self._index
        self._index += 1
        if index in self._recorded:
            return self._recorded[index]
        result = effect()
        self._store.append(
            self._run_id,
            {"kind": _ACTIVITY_COMPLETED, "index": index, "name": name, "result": result},
        )
        return result

    @property
    def activity_count(self) -> int:
        return self._index


@dataclass(frozen=True)
class WorkflowResult:
    run_id: str
    status: Literal["completed"]
    result: Any
    activities: int


class WorkflowEngine:
    """Drives workflow functions against a durable event log"""

    def __init__(self, store: WorkflowEventStore) -> None:
        self._store = store

    def run(self, run_id: str, fn: WorkflowFn) -> WorkflowResult:
        """Start (or idempotently re-run) a workflow to completion"""
        return self._drive(run_id, fn)

    def resume(self, run_id: str, fn: WorkflowFn) -> WorkflowResult:
        """Continue a workflow from its persisted log after a crash"""
        if not self._store.exists(run_id):
            raise KeyError(f"no persisted workflow log for run_id={run_id!r}")
        return self._drive(run_id, fn)

    def _drive(self, run_id: str, fn: WorkflowFn) -> WorkflowResult:
        events = self._store.load(run_id)

        # Idempotent completion: a finished workflow returns its recorded result
        # without re-running the body.
        for event in events:
            if event["kind"] == _WORKFLOW_COMPLETED:
                return WorkflowResult(
                    run_id, "completed", event["result"], _count_activities(events)
                )

        recorded = {
            event["index"]: event["result"]
            for event in events
            if event["kind"] == _ACTIVITY_COMPLETED
        }
        ctx = WorkflowContext(run_id, self._store, recorded)

        try:
            result = fn(ctx)
        except Exception as exc:
            # Deliberately do NOT write a terminal event. Completed activities are
            # already durable, so a later resume replays them and continues.
            logger.warning(
                "workflow interrupted; durable log preserved for resume",
                extra={"run_id": run_id, "error": str(exc), "activities": ctx.activity_count},
            )
            raise

        self._store.append(run_id, {"kind": _WORKFLOW_COMPLETED, "result": result})
        return WorkflowResult(run_id, "completed", result, ctx.activity_count)


def _count_activities(events: list[dict[str, Any]]) -> int:
    return sum(1 for event in events if event["kind"] == _ACTIVITY_COMPLETED)
