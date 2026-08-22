from __future__ import annotations

from pathlib import Path

import pytest
from kairo_ml.agent_runtime.state import WorkflowEventStore
from kairo_ml.agent_runtime.workflow import WorkflowContext, WorkflowEngine, WorkflowFn


def _make_fn(effects: list[int], crash_at: int | None) -> WorkflowFn:
    def fn(ctx: WorkflowContext) -> dict[str, object]:
        for i in range(4):

            def effect(idx: int = i) -> int:
                effects.append(idx)
                return idx

            ctx.execute(f"step{i}", effect)
            if crash_at is not None and i == crash_at:
                raise RuntimeError("simulated crash")
        return {"steps": list(effects)}

    return fn


def test_workflow_replays_to_same_state_after_crash(tmp_path: Path) -> None:
    engine = WorkflowEngine(WorkflowEventStore(tmp_path / "wf"))

    clean_effects: list[int] = []
    clean = engine.run("clean", _make_fn(clean_effects, None))
    assert clean.status == "completed"
    assert clean.result == {"steps": [0, 1, 2, 3]}
    assert clean_effects == [0, 1, 2, 3]
    assert clean.activities == 4

    crash_effects: list[int] = []
    with pytest.raises(RuntimeError):
        engine.run("crash", _make_fn(crash_effects, 1))
    # The crash happened right after step 1 was durably recorded.
    assert crash_effects == [0, 1]

    resumed = engine.resume("crash", _make_fn(crash_effects, None))
    # Steps 0 and 1 were replayed from the log and NOT re-executed; only 2 and 3
    # ran on resume. No effect executed twice.
    assert crash_effects == [0, 1, 2, 3]
    assert resumed.result == clean.result


def test_completed_workflow_is_idempotent(tmp_path: Path) -> None:
    engine = WorkflowEngine(WorkflowEventStore(tmp_path / "wf"))
    effects: list[int] = []
    first = engine.run("run", _make_fn(effects, None))
    assert effects == [0, 1, 2, 3]

    # Re-running a completed workflow returns the recorded result and re-executes
    # nothing.
    again = engine.run("run", _make_fn(effects, None))
    assert again.result == first.result
    assert effects == [0, 1, 2, 3]


def test_resume_requires_persisted_log(tmp_path: Path) -> None:
    engine = WorkflowEngine(WorkflowEventStore(tmp_path / "wf"))
    with pytest.raises(KeyError):
        engine.resume("missing", _make_fn([], None))


def test_activity_result_is_recorded_once(tmp_path: Path) -> None:
    engine = WorkflowEngine(WorkflowEventStore(tmp_path / "wf"))
    calls: list[str] = []

    def effect() -> int:
        calls.append("called")
        return 42

    def fn(ctx: WorkflowContext) -> int:
        return int(ctx.execute("only", effect))

    assert engine.run("r", fn).result == 42
    # Second drive replays the recorded result without invoking the effect again.
    assert engine.run("r", fn).result == 42
    assert calls == ["called"]
