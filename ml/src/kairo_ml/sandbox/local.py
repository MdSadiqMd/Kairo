"""Local filesystem + subprocess sandbox

`LocalSandbox` implements the `Sandbox` protocol
for offline use: every RL environment, the strict coding harness, and local
agent runs share it. It provides an ephemeral working directory, path-scoped
file I/O, timeout-enforced command execution in an isolated process group, and
best-effort network denial.

Hard network isolation in production is a Kubernetes NetworkPolicy, not
this class: `no_network` here scrubs proxy/network env and, when the `unshare`
binary is present, runs the command in a fresh empty network namespace. When
`unshare` is unavailable (macOS, unprivileged containers) it degrades to env
scrubbing only, and the NetworkPolicy remains the real boundary
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from types import TracebackType

from kairo_common import get_logger

from kairo_ml.sandbox.base import RunResult

log = get_logger("kairo-ml.sandbox.local")

_NETWORK_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "ftp_proxy",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "FTP_PROXY",
    "NO_PROXY",
)


class LocalSandbox:
    """An ephemeral, filesystem-scoped execution environment.

    Single-use: construct, run a task, score, ``cleanup`` (or use as a context
    manager). All relative paths are confined to ``root``; traversal outside is
    rejected. Not thread-safe — one caller per sandbox.
    """

    def __init__(self, *, no_network: bool = True, prefix: str = "kairo-sandbox-") -> None:
        self._root = tempfile.mkdtemp(prefix=prefix)
        self._no_network = no_network
        self._cleaned = False
        log.debug("sandbox created", extra={"root": self._root, "no_network": no_network})

    @property
    def root(self) -> str:
        return self._root

    def _resolve(self, relpath: str) -> Path:
        """Resolve ``relpath`` under ``root``, rejecting traversal.

        Guards against ``..`` segments and absolute paths by resolving the
        candidate and confirming it stays within the (realpath-resolved) root.
        Symlink games are covered because both sides are fully resolved.
        """
        if os.path.isabs(relpath):
            raise ValueError(f"absolute paths are not allowed: {relpath!r}")
        root = Path(self._root).resolve()
        candidate = (root / relpath).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError(f"path escapes sandbox root: {relpath!r}")
        return candidate

    def write_file(self, relpath: str, content: str) -> None:
        target = self._resolve(relpath)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def read_file(self, relpath: str) -> str:
        return self._resolve(relpath).read_text(encoding="utf-8")

    def exists(self, relpath: str) -> bool:
        try:
            return self._resolve(relpath).exists()
        except ValueError:
            return False

    def remove(self, relpath: str) -> None:
        target = self._resolve(relpath)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def _build_env(self, env: dict[str, str] | None) -> dict[str, str]:
        base = dict(os.environ) if env is None else dict(env)
        if self._no_network:
            # Scrub proxy config so a subprocess can't reach a configured
            # egress proxy; the namespace (below) is the real block when present.
            for key in _NETWORK_ENV_KEYS:
                base.pop(key, None)
        return base

    def _wrap_argv(self, argv: list[str]) -> list[str]:
        """Prefix with ``unshare -n`` for a private network namespace if possible."""
        if self._no_network and shutil.which("unshare") is not None:
            return ["unshare", "-n", "--", *argv]
        return argv

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: float = 30.0,
        stdin: str | None = None,
        env: dict[str, str] | None = None,
    ) -> RunResult:
        if not argv:
            raise ValueError("argv must not be empty")
        popen_argv = self._wrap_argv(argv)
        proc = subprocess.Popen(
            popen_argv,
            cwd=self._root,
            env=self._build_env(env),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # Own process group so a timeout can kill the whole tree, not just
            # the immediate child (which may have spawned its own children).
            start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_group(proc)
            stdout, stderr = proc.communicate()
        exit_code = proc.returncode if proc.returncode is not None else -1
        return RunResult(
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=timed_out,
        )

    @staticmethod
    def _kill_group(proc: subprocess.Popen[str]) -> None:
        """Kill the child's whole process group (SIGKILL) after a timeout."""
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)

    def reinit_git(self, *, message: str = "Initial commit") -> bool:
        """Remove ``.git`` and reinitialize a single-commit history.

        Prevents public-answer lookup via commit history on evals built from
        historical repos. Feature-detects ``git``; returns ``False`` and skips
        cleanly if the binary is absent so offline environments don't hard-fail.
        """
        if shutil.which("git") is None:
            log.warning("git not found; skipping reinit_git")
            return False
        git_dir = Path(self._root) / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir)
        commit_env = {
            "GIT_AUTHOR_NAME": "kairo-sandbox",
            "GIT_AUTHOR_EMAIL": "sandbox@kairo.local",
            "GIT_COMMITTER_NAME": "kairo-sandbox",
            "GIT_COMMITTER_EMAIL": "sandbox@kairo.local",
        }
        run_env = {**self._build_env(None), **commit_env}
        for step in (
            ["git", "init", "-q"],
            ["git", "add", "-A"],
            ["git", "commit", "-q", "-m", message, "--allow-empty"],
        ):
            result = subprocess.run(
                step,
                cwd=self._root,
                env=run_env,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                log.warning(
                    "reinit_git step failed",
                    extra={"step": step, "stderr": result.stderr.strip()},
                )
                return False
        return True

    def cleanup(self) -> None:
        if self._cleaned:
            return
        shutil.rmtree(self._root, ignore_errors=True)
        self._cleaned = True
        log.debug("sandbox cleaned", extra={"root": self._root})

    def __enter__(self) -> LocalSandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.cleanup()
