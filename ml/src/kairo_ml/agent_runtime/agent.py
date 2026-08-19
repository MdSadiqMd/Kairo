"""Planner / worker loop

The loop follows the sequence diagram exactly:

    planner proposes an action
      -> if risky, the autonomy gate classifies it BEFORE execution
         -> allow: execute in the sandbox
         -> hold : record feedback + safer alternative and let the planner
                   choose another path (recover, do not abort)
      -> checkpoint the combined workflow+machine state after every step
      -> a completion evaluator ends the run; the transcript is archived

The action-proposing "model" is injected as the `Planner` protocol so tests
drive it with a scripted/function planner and production wires the router. Every
step is checkpointed (hibernate/resume), and `max_steps` / `deadline_s`
guard against runaway loops
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from kairo_common import get_logger, new_request_id
from pydantic import BaseModel, Field

from kairo_ml.agent_runtime.autonomy import AutonomyGate
from kairo_ml.agent_runtime.checkpoint import CheckpointStore
from kairo_ml.agent_runtime.state import StateStores
from kairo_ml.agent_runtime.tools import Permission, ToolContext, ToolError, ToolRegistry
from kairo_ml.sandbox.base import Sandbox

logger = get_logger(__name__)


class PlannerAction(BaseModel):
    kind: Literal["tool", "finish"]
    tool: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    # Canonical autonomy action for the gate; None means the tool is non-risky
    autonomy_action: str | None = None
    target: str | None = None
    summary: str | None = None


@dataclass(frozen=True)
class Observation:
    step: int
    kind: Literal["tool_result", "blocked", "error"]
    action: str
    content: Any


@dataclass
class PlannerContext:
    task: str
    step: int
    observations: list[Observation]

    @property
    def last_observation(self) -> Observation | None:
        return self.observations[-1] if self.observations else None


class Planner(Protocol):
    def propose(self, ctx: PlannerContext) -> PlannerAction: ...


class ScriptedPlanner:
    """Returns a fixed sequence of actions, then finish (for CLI/simple
    tests). For branching recovery behavior use FunctionPlanner"""

    def __init__(self, actions: list[PlannerAction]) -> None:
        self._actions = actions
        self._cursor = 0

    def propose(self, ctx: PlannerContext) -> PlannerAction:
        if self._cursor >= len(self._actions):
            return PlannerAction(kind="finish", summary="script exhausted")
        action = self._actions[self._cursor]
        self._cursor += 1
        return action


class FunctionPlanner:
    """Wraps a (PlannerContext) -> PlannerAction callable so a planner can
    branch on observations (e.g. recover from a blocked action)"""

    def __init__(self, fn: Callable[[PlannerContext], PlannerAction]) -> None:
        self._fn = fn

    def propose(self, ctx: PlannerContext) -> PlannerAction:
        return self._fn(ctx)


class CompletionEvaluator(Protocol):
    def is_complete(self, ctx: PlannerContext, action: PlannerAction) -> bool: ...


class DefaultCompletion:
    def is_complete(self, ctx: PlannerContext, action: PlannerAction) -> bool:
        return action.kind == "finish"


@dataclass
class AgentConfig:
    max_steps: int = 20
    deadline_s: float = 60.0
    max_permission: Permission = Permission.HIGH


@dataclass
class AgentCheckpoint:
    """Combined workflow + machine snapshot for hibernate/resume"""

    run_id: str
    step: int
    completed: bool
    status: str
    observations: list[dict[str, Any]]
    machine_snapshot: dict[str, str]
    final_output: str | None

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AgentCheckpoint:
        return cls(**payload)

    def restored_observations(self) -> list[Observation]:
        return [Observation(**record) for record in self.observations]


@dataclass
class AgentRunResult:
    run_id: str
    status: Literal["completed", "max_steps", "deadline"]
    steps: int
    observations: list[Observation]
    final_output: str | None
    transcript: list[dict[str, Any]] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        *,
        planner: Planner,
        tools: ToolRegistry,
        gate: AutonomyGate,
        sandbox: Sandbox,
        checkpoints: CheckpointStore,
        stores: StateStores | None = None,
        config: AgentConfig | None = None,
        completion: CompletionEvaluator | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._planner = planner
        self._tools = tools
        self._gate = gate
        self._sandbox = sandbox
        self._checkpoints = checkpoints
        self._stores = stores
        self._config = config or AgentConfig()
        self._completion = completion or DefaultCompletion()
        self._clock = clock

    def load_checkpoint(self, run_id: str) -> AgentCheckpoint | None:
        payload = self._checkpoints.load(run_id)
        return AgentCheckpoint.from_payload(payload) if payload else None

    def run(
        self,
        task: str,
        *,
        run_id: str | None = None,
        resume_from: AgentCheckpoint | None = None,
    ) -> AgentRunResult:
        if run_id is None:
            run_id = resume_from.run_id if resume_from else new_request_id()

        observations = list(resume_from.restored_observations()) if resume_from else []
        step = resume_from.step if resume_from else 0

        tool_ctx = ToolContext(sandbox=self._sandbox)
        if resume_from:
            self._restore_machine_state(tool_ctx, resume_from.machine_snapshot)

        status: Literal["completed", "max_steps", "deadline"] = "max_steps"
        final_output: str | None = resume_from.final_output if resume_from else None
        started = self._clock()

        while True:
            if step >= self._config.max_steps:
                status = "max_steps"
                break
            if self._clock() - started > self._config.deadline_s:
                status = "deadline"
                break

            ctx = PlannerContext(task=task, step=step, observations=observations)
            action = self._planner.propose(ctx)
            self._conversation(run_id, "assistant", f"propose:{action.kind}", action.model_dump())

            if action.kind == "finish":
                if self._completion.is_complete(ctx, action):
                    status = "completed"
                    final_output = action.summary or final_output or ""
                    break
                # Completion rejected: record it and keep going (bounded by max_steps)
                observations.append(
                    Observation(step, "error", "finish", {"error": "completion rejected"})
                )
                step += 1
                continue

            observation = self._execute_step(run_id, step, action, tool_ctx)
            observations.append(observation)
            self._checkpoint(run_id, step + 1, tool_ctx, observations, False, "running", None)
            step += 1

        self._checkpoint(
            run_id, step, tool_ctx, observations, status == "completed", status, final_output
        )
        transcript = self._archive_transcript(run_id, task, observations, status, final_output)
        logger.info(
            "agent run finished",
            extra={"run_id": run_id, "status": status, "steps": step},
        )
        return AgentRunResult(
            run_id=run_id,
            status=status,
            steps=step,
            observations=observations,
            final_output=final_output,
            transcript=transcript,
        )

    def _execute_step(
        self, run_id: str, step: int, action: PlannerAction, tool_ctx: ToolContext
    ) -> Observation:
        if action.autonomy_action:
            decision = self._gate.evaluate(action=action.autonomy_action, target=action.target)
            self._tool_log(
                run_id,
                {
                    "step": step,
                    "phase": "autonomy",
                    "action": action.autonomy_action,
                    "target": action.target,
                    **decision.as_dict(),
                    "allowed": decision.allowed,
                },
            )
            if not decision.allowed:
                # return feedback to the parent agent so it can choose a
                # safer path without aborting or interrupting the user
                return Observation(
                    step,
                    "blocked",
                    action.autonomy_action,
                    {
                        "feedback": decision.feedback,
                        "safer_alternative": decision.verdict.safer_alternative,
                    },
                )

        if action.tool is None:
            return Observation(step, "error", "", {"error": "tool action missing tool name"})

        try:
            result = self._tools.invoke(
                action.tool,
                action.args,
                tool_ctx,
                max_permission=self._config.max_permission,
            )
        except ToolError as exc:
            self._tool_log(
                run_id,
                {"step": step, "phase": "tool", "tool": action.tool, "error": str(exc)},
            )
            return Observation(step, "error", action.tool, {"error": str(exc)})

        self._tool_log(run_id, {"step": step, "phase": "tool", "tool": action.tool, "ok": True})
        return Observation(step, "tool_result", action.tool, result)

    def _restore_machine_state(self, tool_ctx: ToolContext, snapshot: dict[str, str]) -> None:
        # Re-materialize the sandbox filesystem from the machine-state manifest
        # so a resumed run sees the files a prior run produced (resume)
        for relpath, content in snapshot.items():
            self._sandbox.write_file(relpath, content)
            tool_ctx.written_files[relpath] = content

    def _checkpoint(
        self,
        run_id: str,
        step: int,
        tool_ctx: ToolContext,
        observations: list[Observation],
        completed: bool,
        status: str,
        final_output: str | None,
    ) -> None:
        checkpoint = AgentCheckpoint(
            run_id=run_id,
            step=step,
            completed=completed,
            status=status,
            observations=[asdict(obs) for obs in observations],
            machine_snapshot=dict(tool_ctx.written_files),
            final_output=final_output,
        )
        self._checkpoints.save(run_id, checkpoint.to_payload())
        if self._stores is not None:
            self._stores.machine.save(
                run_id,
                {"sandbox_root": self._sandbox.root, "files": dict(tool_ctx.written_files)},
            )

    def _archive_transcript(
        self,
        run_id: str,
        task: str,
        observations: list[Observation],
        status: str,
        final_output: str | None,
    ) -> list[dict[str, Any]]:
        transcript = [asdict(obs) for obs in observations]
        if self._stores is not None:
            import json

            self._stores.artifacts.put_text(
                f"{run_id}/transcript.json",
                json.dumps(
                    {
                        "run_id": run_id,
                        "task": task,
                        "status": status,
                        "final_output": final_output,
                        "steps": transcript,
                    },
                    default=str,
                ),
            )
        return transcript

    def _conversation(self, run_id: str, role: str, content: str, metadata: dict[str, Any]) -> None:
        if self._stores is not None:
            self._stores.conversation.append(role, content, metadata)

    def _tool_log(self, run_id: str, entry: dict[str, Any]) -> None:
        if self._stores is not None:
            self._stores.tool_logs.append(entry)
