from __future__ import annotations

import os
import sys

import pytest
from kairo_ml.sandbox import LocalSandbox, RunResult, Sandbox


def test_sandbox_satisfies_protocol() -> None:
    with LocalSandbox() as sb:
        assert isinstance(sb, Sandbox)


def test_run_captures_stdout_and_exit_code() -> None:
    with LocalSandbox() as sb:
        result = sb.run([sys.executable, "-c", "print('hello')"])
        assert isinstance(result, RunResult)
        assert result.exit_code == 0
        assert result.ok
        assert "hello" in result.stdout
        assert not result.timed_out


def test_run_nonzero_exit() -> None:
    with LocalSandbox() as sb:
        result = sb.run([sys.executable, "-c", "import sys; sys.exit(3)"])
        assert result.exit_code == 3
        assert not result.ok


def test_timeout_kills_process_group() -> None:
    with LocalSandbox() as sb:
        result = sb.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout_s=0.5)
        assert result.timed_out
        assert not result.ok


def test_file_io_roundtrip() -> None:
    with LocalSandbox() as sb:
        sb.write_file("dir/a.txt", "content")
        assert sb.exists("dir/a.txt")
        assert sb.read_file("dir/a.txt") == "content"


def test_traversal_rejected() -> None:
    with LocalSandbox() as sb:
        with pytest.raises(ValueError):
            sb.write_file("../escape.txt", "x")
        with pytest.raises(ValueError):
            sb.read_file("../../etc/passwd")
        assert not sb.exists("../escape.txt")


def test_absolute_path_rejected() -> None:
    with LocalSandbox() as sb, pytest.raises(ValueError):
        sb.write_file("/etc/passwd", "x")


def test_cleanup_removes_root() -> None:
    sb = LocalSandbox()
    root = sb.root
    sb.write_file("f.txt", "x")
    assert os.path.isdir(root)
    sb.cleanup()
    assert not os.path.exists(root)
    sb.cleanup()  # idempotent


def test_no_network_scrubs_proxy_env() -> None:
    with LocalSandbox(no_network=True) as sb:
        result = sb.run(
            [sys.executable, "-c", "import os; print(os.environ.get('HTTP_PROXY', 'UNSET'))"],
            env={"HTTP_PROXY": "http://evil:8080", "PATH": os.environ.get("PATH", "")},
        )
        assert "UNSET" in result.stdout


def test_reinit_git_creates_single_commit() -> None:
    import shutil

    if shutil.which("git") is None:
        pytest.skip("git not available")
    with LocalSandbox() as sb:
        sb.write_file("code.py", "x = 1\n")
        assert sb.reinit_git() is True
        assert sb.exists(".git")
        log = sb.run(["git", "log", "--oneline"])
        assert log.exit_code == 0
        assert len(log.stdout.strip().splitlines()) == 1
