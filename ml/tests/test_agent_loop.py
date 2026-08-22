from __future__ import annotations

from pathlib import Path
from typing import Any

from kairo_ml.agent_runtime.agent import (
    Agent,
    AgentConfig,
    FunctionPlanner,
    PlannerAction,
    PlannerContext,
    ScriptedPlanner,
)
from kairo_ml.agent_runtime.autonomy import AutonomyGate
from kairo_ml.agent_runtime.checkpoint import CheckpointStore, LocalCheckpointStore
from kairo_ml.agent_runtime.state import StateStores
from kairo_ml.agent_runtime.tools import default_tool_registry
from kairo_ml.sandbox.base import Sandbox


class RecordingCheckpoints:
    """Wraps a CheckpointStore to record the step of every save."""

    def __init__(self, inner: CheckpointStore) -> None:
        self._inner = inner
        self.saved_steps: list[int] = []

    def save(self, checkpoint_id: str, payload: dict[str, Any]) -> None:
        self.saved_steps.append(payload["step"])
        self._inner.save(checkpoint_id, payload)

    def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        return self._inner.load(checkpoint_id)

    def list_ids(self) -> list[str]:
        return self._inner.list_ids()


def _build_agent(
    sandbox: Sandbox,
    planner: Any,
    tmp_path: Path,
    *,
    checkpoints: CheckpointStore | None = None,
    config: AgentConfig | None = None,
) -> Agent:
    return Agent(
        planner=planner,
        tools=default_tool_registry(),
        gate=AutonomyGate(),
        sandbox=sandbox,
        checkpoints=checkpoints or LocalCheckpointStore(tmp_path / "ckpt"),
        stores=StateStores.local(tmp_path / "state", "run1"),
        config=config or AgentConfig(max_steps=10),
    )


def test_scripted_multistep_completes_and_checkpoints_each_step(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    actions = [
        PlannerAction(
            kind="tool",
            tool="write_file",
            args={"path": "a.txt", "content": "hi"},
            autonomy_action="write_scratch",
            target="a.txt",
        ),
        PlannerAction(
            kind="tool",
            tool="read_file",
            args={"path": "a.txt"},
            autonomy_action="read_file",
        ),
        PlannerAction(kind="finish", summary="done"),
    ]
    checkpoints = RecordingCheckpoints(LocalCheckpointStore(tmp_path / "ckpt"))
    agent = _build_agent(sandbox, ScriptedPlanner(actions), tmp_path, checkpoints=checkpoints)

    result = agent.run("task", run_id="run1")

    assert result.status == "completed"
    assert result.steps == 2
    assert result.final_output == "done"
    assert result.observations[0].kind == "tool_result"
    assert result.observations[1].content["content"] == "hi"

    # A checkpoint was written after each executed step, plus a final one.
    assert checkpoints.saved_steps == [1, 2, 2]

    final = agent.load_checkpoint("run1")
    assert final is not None
    assert final.completed is True
    assert final.step == 2
    assert final.machine_snapshot == {"a.txt": "hi"}

    # State separation: conversation, tool logs, and artifacts each populated.
    stores = StateStores.local(tmp_path / "state", "run1")
    assert stores.conversation.count() >= 3
    assert len(stores.tool_logs.entries()) >= 2
    assert stores.artifacts.get_text("run1/transcript.json") is not None


def test_blocked_action_recovers_with_safer_alternative(sandbox: Sandbox, tmp_path: Path) -> None:
    def plan(ctx: PlannerContext) -> PlannerAction:
        last = ctx.last_observation
        if ctx.step == 0:
            # A risky action the gate will block.
            return PlannerAction(
                kind="tool",
                tool="read_file",
                args={"path": "secret"},
                autonomy_action="read_secrets",
                target="secret",
            )
        if last is not None and last.kind == "blocked":
            # Recover along the safer path instead of aborting.
            return PlannerAction(
                kind="tool",
                tool="write_file",
                args={"path": "safe.txt", "content": "ok"},
                autonomy_action="write_scratch",
                target="safe.txt",
            )
        return PlannerAction(kind="finish", summary="recovered")

    agent = _build_agent(sandbox, FunctionPlanner(plan), tmp_path)
    result = agent.run("task", run_id="run1")

    assert result.status == "completed"
    assert result.final_output == "recovered"
    assert result.observations[0].kind == "blocked"
    assert result.observations[0].content["safer_alternative"]
    assert result.observations[1].kind == "tool_result"
    # The blocked secret read never touched the sandbox.
    assert not sandbox.exists("secret")
    assert sandbox.read_file("safe.txt") == "ok"


def test_restore_from_checkpoint_resumes(sandbox_factory: Any, tmp_path: Path) -> None:
    def plan(ctx: PlannerContext) -> PlannerAction:
        if ctx.step == 0:
            return PlannerAction(
                kind="tool",
                tool="write_file",
                args={"path": "a.txt", "content": "hi"},
                autonomy_action="write_scratch",
                target="a.txt",
            )
        if ctx.step == 1:
            return PlannerAction(
                kind="tool",
                tool="read_file",
                args={"path": "a.txt"},
                autonomy_action="read_file",
            )
        return PlannerAction(kind="finish", summary="done")

    checkpoints = LocalCheckpointStore(tmp_path / "ckpt")

    # First leg: stop after one step (hibernate).
    sandbox_a = sandbox_factory()
    agent_a = _build_agent(
        sandbox_a,
        FunctionPlanner(plan),
        tmp_path,
        checkpoints=checkpoints,
        config=AgentConfig(max_steps=1),
    )
    first = agent_a.run("task", run_id="run1")
    assert first.status == "max_steps"
    assert first.steps == 1

    checkpoint = agent_a.load_checkpoint("run1")
    assert checkpoint is not None
    assert checkpoint.completed is False
    assert checkpoint.machine_snapshot == {"a.txt": "hi"}

    # Second leg: a fresh sandbox + agent restores machine state and resumes.
    sandbox_b = sandbox_factory()
    assert not sandbox_b.exists("a.txt")
    agent_b = _build_agent(
        sandbox_b,
        FunctionPlanner(plan),
        tmp_path,
        checkpoints=checkpoints,
        config=AgentConfig(max_steps=10),
    )
    second = agent_b.run("task", run_id="run1", resume_from=checkpoint)

    assert second.status == "completed"
    # Machine state was restored into the fresh sandbox before resuming.
    assert sandbox_b.read_file("a.txt") == "hi"
    read_obs = [
        o for o in second.observations if o.kind == "tool_result" and o.action == "read_file"
    ]
    assert read_obs and read_obs[-1].content["content"] == "hi"


def test_max_steps_guard_stops_runaway_loop(sandbox: Sandbox, tmp_path: Path) -> None:
    def never_finish(ctx: PlannerContext) -> PlannerAction:
        return PlannerAction(
            kind="tool",
            tool="write_file",
            args={"path": f"f{ctx.step}.txt", "content": "x"},
            autonomy_action="write_scratch",
            target="f.txt",
        )

    agent = _build_agent(
        sandbox,
        FunctionPlanner(never_finish),
        tmp_path,
        config=AgentConfig(max_steps=3),
    )
    result = agent.run("task", run_id="run1")
    assert result.status == "max_steps"
    assert result.steps == 3


def test_deadline_guard_stops_loop(sandbox: Sandbox, tmp_path: Path) -> None:
    ticks = iter([0.0, 100.0, 100.0])

    agent = Agent(
        planner=FunctionPlanner(lambda ctx: PlannerAction(kind="finish", summary="unreached")),
        tools=default_tool_registry(),
        gate=AutonomyGate(),
        sandbox=sandbox,
        checkpoints=LocalCheckpointStore(tmp_path / "ckpt"),
        config=AgentConfig(max_steps=10, deadline_s=1.0),
        clock=lambda: next(ticks),
    )
    result = agent.run("task", run_id="run1")
    assert result.status == "deadline"
