"""kairo-agent CLI

Runs a task end-to-end with a local sandbox and a scripted/echo planner. The
sandbox here is a small, self-contained filesystem+subprocess implementation of
the kairo_ml.sandbox.base.Sandbox protocol so the CLI works fully offline;
production wires kairo_ml.sandbox.local.LocalSandbox and the router-backed
planner in its place
"""

from __future__ import annotations

import argparse
import json
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from kairo_common import configure_logging, get_logger

from kairo_ml.agent_runtime.agent import (
    Agent,
    AgentConfig,
    Planner,
    PlannerAction,
    ScriptedPlanner,
)
from kairo_ml.agent_runtime.autonomy import AutonomyGate
from kairo_ml.agent_runtime.checkpoint import LocalCheckpointStore
from kairo_ml.agent_runtime.state import StateStores
from kairo_ml.agent_runtime.tools import default_tool_registry
from kairo_ml.agent_runtime.worker import AgentWorker, DirTaskQueue, WorkerConfig
from kairo_ml.sandbox.base import RunResult

logger = get_logger(__name__)


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


class _CliSandbox:
    """Minimal offline Sandbox implementation for the CLI (protocol-conformant)"""

    def __init__(self) -> None:
        self._root = tempfile.mkdtemp(prefix="kairo-agent-")

    @property
    def root(self) -> str:
        return self._root

    def _resolve(self, relpath: str) -> Path:
        target = (Path(self._root) / relpath).resolve()
        if not str(target).startswith(str(Path(self._root).resolve())):
            raise ValueError(f"path escapes sandbox: {relpath}")
        return target

    def write_file(self, relpath: str, content: str) -> None:
        path = self._resolve(relpath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_file(self, relpath: str) -> str:
        return self._resolve(relpath).read_text(encoding="utf-8")

    def exists(self, relpath: str) -> bool:
        return self._resolve(relpath).exists()

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: float = 30.0,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        try:
            completed = subprocess.run(
                argv,
                cwd=self._root,
                input=stdin,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return RunResult(124, _as_text(exc.stdout), _as_text(exc.stderr), True)
        return RunResult(completed.returncode, completed.stdout, completed.stderr, False)

    def cleanup(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)


def _echo_plan(task: str) -> list[PlannerAction]:
    """A deterministic scripted plan that exercises the sandbox + tools"""
    return [
        PlannerAction(
            kind="tool",
            tool="write_file",
            args={"path": "task.txt", "content": task},
            autonomy_action="write_scratch",
            target="task.txt",
        ),
        PlannerAction(
            kind="tool",
            tool="run_command",
            args={"argv": ["cat", "task.txt"]},
            autonomy_action="run_command",
        ),
        PlannerAction(kind="finish", summary=f"completed task: {task}"),
    ]


def _make_planner(task: str) -> Planner:
    return ScriptedPlanner(_echo_plan(task))


def _cmd_run(ns: argparse.Namespace) -> int:
    state_dir = (
        Path(ns.state_dir) if ns.state_dir else Path(tempfile.mkdtemp(prefix="kairo-state-"))
    )
    run_id = "cli-run"
    sandbox = _CliSandbox()
    try:
        agent = Agent(
            planner=_make_planner(ns.task),
            tools=default_tool_registry(),
            gate=AutonomyGate(),
            sandbox=sandbox,
            checkpoints=LocalCheckpointStore(state_dir / "checkpoints"),
            stores=StateStores.local(state_dir, run_id),
            config=AgentConfig(max_steps=ns.max_steps),
        )
        result = agent.run(ns.task, run_id=run_id)
    finally:
        sandbox.cleanup()

    json.dump(
        {
            "run_id": result.run_id,
            "status": result.status,
            "steps": result.steps,
            "final_output": result.final_output,
            "observations": result.transcript,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0 if result.status == "completed" else 1


def _cmd_worker(ns: argparse.Namespace) -> int:
    """Resident poll loop for the k8s agent-worker Deployment"""
    stop = {"flag": False}

    def _handle(_sig: int, _frame: object) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)

    worker = AgentWorker(
        queue=DirTaskQueue(ns.queue_dir),
        make_sandbox=_CliSandbox,
        make_planner=_make_planner,
        state_root=ns.state_dir or tempfile.mkdtemp(prefix="kairo-worker-"),
        config=WorkerConfig(poll_interval_s=ns.poll_interval, max_steps=ns.max_steps),
    )
    processed = worker.serve(should_stop=lambda: stop["flag"])
    logger.info("agent worker stopped", extra={"processed": processed})
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging("kairo-agent")
    parser = argparse.ArgumentParser(prog="kairo-agent", description="Durable agent runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run a task end to end")
    run_parser.add_argument("--task", required=True, help="Task specification")
    run_parser.add_argument("--max-steps", type=int, default=20)
    run_parser.add_argument(
        "--state-dir", default=None, help="Directory for state/checkpoints (default: temp)"
    )

    worker_parser = sub.add_parser("worker", help="Run the resident task-queue worker")
    worker_parser.add_argument("--queue-dir", required=True, help="Filesystem task-queue directory")
    worker_parser.add_argument("--state-dir", default=None)
    worker_parser.add_argument("--poll-interval", type=float, default=2.0)
    worker_parser.add_argument("--max-steps", type=int, default=20)

    ns = parser.parse_args(argv)
    if ns.command == "run":
        return _cmd_run(ns)
    if ns.command == "worker":
        return _cmd_worker(ns)
    parser.error(f"unknown command: {ns.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
