"""Typed tool registry (with tool action classifier)

Every tool declares a pydantic args schema, a permission/risk tier, and the
canonical autonomy action it maps to (the same action names the autonomy gate
classifies). Registration validates args against the schema at call time and
rejects unregistered or over-permissioned tools — the requirement that
"tool calls [are] validated against schema and policy" before they run

Tools receive a ToolContext carrying the injected Sandbox (the runtime
depends on the kairo_ml.sandbox.base.Sandbox *protocol*, never a concrete
implementation) plus a written_files map that doubles as the machine-state
manifest for checkpointing
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from kairo_common import get_logger
from pydantic import BaseModel, Field, ValidationError

from kairo_ml.sandbox.base import Sandbox

logger = get_logger(__name__)


class Permission(IntEnum):
    """Ordered risk tiers so a permission ceiling is a simple comparison"""

    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ToolError(Exception):
    """Base class for tool invocation failures"""


class UnknownToolError(ToolError):
    """Raised when invoking a tool that is not registered"""


class ToolPermissionError(ToolError):
    """Raised when a tool's permission tier exceeds the caller's ceiling"""


class ToolArgsError(ToolError):
    """Raised when arguments fail schema validation"""


@dataclass
class ToolContext:
    sandbox: Sandbox
    # Doubles as the machine-state manifest: every scratch write is recorded so a
    # checkpoint can reconstruct the sandbox filesystem on resume.
    written_files: dict[str, str] = field(default_factory=dict)


ToolHandler = Callable[[Any, ToolContext], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    permission: Permission
    autonomy_action: str | None

    def json_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.name.lower(),
            "autonomy_action": self.autonomy_action,
            "parameters": self.args_model.model_json_schema(),
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def tool(
        self,
        *,
        name: str,
        args_model: type[BaseModel],
        permission: Permission,
        autonomy_action: str | None = None,
        description: str = "",
    ) -> Callable[[ToolHandler], ToolHandler]:
        def decorator(handler: ToolHandler) -> ToolHandler:
            self.register(
                ToolSpec(
                    name=name,
                    description=description or (handler.__doc__ or "").strip(),
                    args_model=args_model,
                    handler=handler,
                    permission=permission,
                    autonomy_action=autonomy_action,
                )
            )
            return handler

        return decorator

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise UnknownToolError(f"unknown tool: {name}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def json_schemas(self) -> dict[str, dict[str, Any]]:
        return {name: spec.json_schema() for name, spec in sorted(self._tools.items())}

    def invoke(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: ToolContext,
        *,
        max_permission: Permission = Permission.CRITICAL,
    ) -> Any:
        spec = self.get(name)  # raises UnknownToolError for unregistered tools
        if spec.permission > max_permission:
            raise ToolPermissionError(
                f"tool '{name}' requires {spec.permission.name} but ceiling is "
                f"{max_permission.name}"
            )
        try:
            args = spec.args_model(**raw_args)
        except ValidationError as exc:
            raise ToolArgsError(f"invalid args for tool '{name}': {exc}") from exc
        return spec.handler(args, ctx)


class ReadFileArgs(BaseModel):
    path: str


class WriteFileArgs(BaseModel):
    path: str
    content: str


class RunCommandArgs(BaseModel):
    argv: list[str] = Field(min_length=1)
    timeout_s: float = 30.0


class HttpGetArgs(BaseModel):
    url: str


def default_tool_registry() -> ToolRegistry:
    """A registry pre-populated with the example tools"""
    registry = ToolRegistry()

    @registry.tool(
        name="read_file",
        args_model=ReadFileArgs,
        permission=Permission.LOW,
        autonomy_action="read_file",
        description="Read a text file from the sandbox.",
    )
    def read_file(args: ReadFileArgs, ctx: ToolContext) -> dict[str, Any]:
        return {"path": args.path, "content": ctx.sandbox.read_file(args.path)}

    @registry.tool(
        name="write_file",
        args_model=WriteFileArgs,
        permission=Permission.LOW,
        autonomy_action="write_scratch",
        description="Write a text file into the sandbox scratch space.",
    )
    def write_file(args: WriteFileArgs, ctx: ToolContext) -> dict[str, Any]:
        ctx.sandbox.write_file(args.path, args.content)
        ctx.written_files[args.path] = args.content
        return {"path": args.path, "bytes": len(args.content.encode("utf-8"))}

    @registry.tool(
        name="run_command",
        args_model=RunCommandArgs,
        permission=Permission.MEDIUM,
        autonomy_action="run_command",
        description="Run a command inside the sandbox with an enforced timeout.",
    )
    def run_command(args: RunCommandArgs, ctx: ToolContext) -> dict[str, Any]:
        result = ctx.sandbox.run(args.argv, timeout_s=args.timeout_s)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
        }

    @registry.tool(
        name="http_get",
        args_model=HttpGetArgs,
        permission=Permission.MEDIUM,
        autonomy_action="external_network_call",
        description="Fetch a URL. Offline stub: no network egress is performed.",
    )
    def http_get(args: HttpGetArgs, _ctx: ToolContext) -> dict[str, Any]:
        # Stub: external egress is gated by the autonomy classifier and disabled
        # offline. A production build injects an allowlisted HTTP client.
        return {"url": args.url, "status": 501, "body": "http_get is disabled offline"}

    return registry
