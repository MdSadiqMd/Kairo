from __future__ import annotations

import pytest
from kairo_ml.agent_runtime.tools import (
    Permission,
    ToolArgsError,
    ToolContext,
    ToolPermissionError,
    UnknownToolError,
    default_tool_registry,
)
from kairo_ml.sandbox.base import Sandbox


def test_fake_sandbox_satisfies_protocol(sandbox: Sandbox) -> None:
    assert isinstance(sandbox, Sandbox)


def test_registry_validates_and_invokes(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    sandbox.write_file("f.txt", "data")
    result = registry.invoke("read_file", {"path": "f.txt"}, ctx)
    assert result == {"path": "f.txt", "content": "data"}


def test_write_file_tracks_machine_state(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    registry.invoke("write_file", {"path": "a.txt", "content": "hi"}, ctx)
    assert ctx.written_files == {"a.txt": "hi"}
    assert sandbox.read_file("a.txt") == "hi"


def test_run_command_via_sandbox(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    result = registry.invoke("run_command", {"argv": ["echo", "hi"]}, ctx)
    assert result["exit_code"] == 0
    assert result["timed_out"] is False


def test_rejects_bad_args(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    with pytest.raises(ToolArgsError):
        registry.invoke("write_file", {"path": "x"}, ctx)  # missing content
    with pytest.raises(ToolArgsError):
        registry.invoke("run_command", {"argv": []}, ctx)  # empty argv


def test_rejects_unregistered_tool(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    with pytest.raises(UnknownToolError):
        registry.invoke("definitely_not_a_tool", {}, ctx)


def test_rejects_over_permissioned_tool(sandbox: Sandbox) -> None:
    registry = default_tool_registry()
    ctx = ToolContext(sandbox=sandbox)
    # run_command is MEDIUM; a LOW ceiling must reject it.
    with pytest.raises(ToolPermissionError):
        registry.invoke("run_command", {"argv": ["echo"]}, ctx, max_permission=Permission.LOW)


def test_json_schema_export() -> None:
    schemas = default_tool_registry().json_schemas()
    assert set(schemas) >= {"read_file", "write_file", "run_command", "http_get"}
    write_props = schemas["write_file"]["parameters"]["properties"]
    assert {"path", "content"} <= set(write_props)
    assert schemas["read_file"]["autonomy_action"] == "read_file"
    assert schemas["run_command"]["permission"] == "medium"
