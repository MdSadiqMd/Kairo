from __future__ import annotations

from pathlib import Path

from kairo_ml.agent_runtime.agent import Planner, PlannerAction, ScriptedPlanner
from kairo_ml.agent_runtime.worker import AgentWorker, DirTaskQueue, WorkerConfig
from kairo_ml.sandbox.base import RunResult, Sandbox


class _FakeSandbox:
    def __init__(self) -> None:
        self._files: dict[str, str] = {}
        self.cleaned = False

    @property
    def root(self) -> str:
        return "/fake"

    def write_file(self, relpath: str, content: str) -> None:
        self._files[relpath] = content

    def read_file(self, relpath: str) -> str:
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
        return RunResult(0, "ok", "", False)

    def cleanup(self) -> None:
        self.cleaned = True


def _planner(task: str) -> Planner:
    return ScriptedPlanner(
        [
            PlannerAction(
                kind="tool",
                tool="write_file",
                args={"path": "task.txt", "content": task},
                autonomy_action="write_scratch",
                target="task.txt",
            ),
            PlannerAction(kind="finish", summary=f"done: {task}"),
        ]
    )


def test_dir_queue_submit_poll_ack(tmp_path: Path) -> None:
    q = DirTaskQueue(tmp_path / "queue")
    tid = q.submit("do a thing")
    msg = q.poll()
    assert msg is not None and msg.task_id == tid and msg.task == "do a thing"
    q.ack(msg)
    assert q.poll() is None  # acked task no longer pending
    assert (tmp_path / "queue" / "done").exists()


def test_worker_processes_queue_until_empty(tmp_path: Path) -> None:
    q = DirTaskQueue(tmp_path / "queue")
    q.submit("task one")
    q.submit("task two")

    made: list[_FakeSandbox] = []

    def make_sandbox() -> Sandbox:
        sb = _FakeSandbox()
        made.append(sb)
        return sb

    worker = AgentWorker(
        queue=q,
        make_sandbox=make_sandbox,
        make_planner=_planner,
        state_root=tmp_path / "state",
        config=WorkerConfig(poll_interval_s=0.0, max_steps=5),
    )
    # Bounded iterations so the loop terminates deterministically offline.
    processed = worker.serve(should_stop=lambda: False, max_iterations=5)
    assert processed == 2
    assert q.poll() is None
    assert all(sb.cleaned for sb in made)  # every sandbox cleaned up


def test_worker_stops_on_signal_flag(tmp_path: Path) -> None:
    q = DirTaskQueue(tmp_path / "queue")
    worker = AgentWorker(
        queue=q,
        make_sandbox=_FakeSandbox,
        make_planner=_planner,
        state_root=tmp_path / "state",
    )
    # should_stop true immediately → no work, clean return.
    assert worker.serve(should_stop=lambda: True) == 0
