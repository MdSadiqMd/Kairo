"""RL environment registry

Maps a stable environment name to its class and constructs instances. Keeping
construction behind `make` lets the CLI, eval runners, and RL rollout workers
resolve environments by name without importing each module directly
"""

from __future__ import annotations

from kairo_ml.rl_envs.base import RLEnvironment
from kairo_ml.rl_envs.browser import BrowserEnv
from kairo_ml.rl_envs.code_repair import CodeRepairEnv
from kairo_ml.rl_envs.math_env import MathEnv
from kairo_ml.rl_envs.sql_env import SqlEnv
from kairo_ml.rl_envs.tool_use import ToolUseEnv

_REGISTRY: dict[str, type[RLEnvironment]] = {
    BrowserEnv.name: BrowserEnv,
    CodeRepairEnv.name: CodeRepairEnv,
    MathEnv.name: MathEnv,
    SqlEnv.name: SqlEnv,
    ToolUseEnv.name: ToolUseEnv,
}


def available() -> list[str]:
    return sorted(_REGISTRY)


def get_env_class(name: str) -> type[RLEnvironment]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown RL environment: {name!r} (available: {available()})")
    return _REGISTRY[name]


def make(name: str, *, no_network: bool = True) -> RLEnvironment:
    return get_env_class(name)(no_network=no_network)
