"""Resident agent worker

The long-running counterpart to the one-shot kairo-agent run: a worker polls
a task queue and executes each task through the durable agent runtime. This is
what the k8s agents/worker-deployment.yaml runs. Temporal-on-EKS is the
production queue/execution backend (agents/temporal.yaml); the filesystem queue
here keeps the worker runnable and testable offline, and an SQS queue is
provided (lazy boto3) for the AWS path

The serve loop is interruptible (SIGTERM) so the Deployment drains cleanly, and
bounded-iteration for tests
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kairo_common import get_logger

from kairo_ml.agent_runtime.agent import Agent, AgentConfig, Planner
from kairo_ml.agent_runtime.autonomy import AutonomyGate
from kairo_ml.agent_runtime.checkpoint import LocalCheckpointStore
from kairo_ml.agent_runtime.state import StateStores
from kairo_ml.agent_runtime.tools import ToolRegistry, default_tool_registry
from kairo_ml.sandbox.base import Sandbox

logger = get_logger(__name__)


@dataclass(frozen=True)
class TaskMessage:
    task_id: str
    task: str
    handle: str  # opaque ack handle (queue-specific)


class TaskQueue(Protocol):
    def poll(self) -> TaskMessage | None: ...
    def ack(self, message: TaskMessage) -> None: ...


class DirTaskQueue:
    """Filesystem task queue: *.json files ({task_id, task}) in a
    directory; acked tasks move to a done/ subdir. Used for dev/tests and as
    the local fallback"""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._done = self._dir / "done"
        self._done.mkdir(exist_ok=True)

    def submit(self, task: str, *, task_id: str | None = None) -> str:
        tid = task_id or f"task_{uuid.uuid4().hex[:12]}"
        (self._dir / f"{tid}.json").write_text(json.dumps({"task_id": tid, "task": task}))
        return tid

    def poll(self) -> TaskMessage | None:
        for path in sorted(self._dir.glob("*.json")):
            data = json.loads(path.read_text())
            return TaskMessage(task_id=data["task_id"], task=data["task"], handle=str(path))
        return None

    def ack(self, message: TaskMessage) -> None:
        src = Path(message.handle)
        if src.exists():
            src.rename(self._done / src.name)


@dataclass
class WorkerConfig:
    poll_interval_s: float = 2.0
    max_steps: int = 20


class AgentWorker:
    def __init__(
        self,
        *,
        queue: TaskQueue,
        make_sandbox: Callable[[], Sandbox],
        make_planner: Callable[[str], Planner],
        state_root: str | Path,
        tools: ToolRegistry | None = None,
        config: WorkerConfig | None = None,
    ) -> None:
        self._queue = queue
        self._make_sandbox = make_sandbox
        self._make_planner = make_planner
        self._state_root = Path(state_root)
        self._tools = tools or default_tool_registry()
        self._config = config or WorkerConfig()

    def run_one(self, message: TaskMessage) -> str:
        """Execute a single task through the durable runtime. Returns status"""
        sandbox = self._make_sandbox()
        run_id = message.task_id
        try:
            agent = Agent(
                planner=self._make_planner(message.task),
                tools=self._tools,
                gate=AutonomyGate(),
                sandbox=sandbox,
                checkpoints=LocalCheckpointStore(self._state_root / run_id / "checkpoints"),
                stores=StateStores.local(self._state_root / run_id, run_id),
                config=AgentConfig(max_steps=self._config.max_steps),
            )
            result = agent.run(message.task, run_id=run_id)
            return result.status
        finally:
            sandbox.cleanup()

    def serve(self, *, should_stop: Callable[[], bool], max_iterations: int | None = None) -> int:
        """Poll-and-execute until should_stop() is true or the (optional)
        iteration bound is hit. Returns the number of tasks processed"""
        processed = 0
        iterations = 0
        while not should_stop():
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            message = self._queue.poll()
            if message is None:
                if max_iterations is not None:
                    continue
                time.sleep(self._config.poll_interval_s)
                continue
            logger.info("agent worker picked up task", extra={"task_id": message.task_id})
            status = self.run_one(message)
            self._queue.ack(message)
            processed += 1
            logger.info(
                "agent worker finished task",
                extra={"task_id": message.task_id, "status": status},
            )
        return processed
