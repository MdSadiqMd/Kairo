"""RL environments

Verifiable-reward environments behind one `RLEnvironment` contract:
`code_repair`, `math`, `sql`, `tool_use`, `browser`. Each honors the
sandbox requirements (ephemeral fs, default-deny network, timeouts, transcript,
scorer-only hidden tests, guaranteed cleanup) and is resolvable by name via the
registry.
"""

from kairo_ml.rl_envs.base import (
    Action,
    Done,
    Info,
    Observation,
    Reward,
    RLEnvironment,
    ScoreReport,
)
from kairo_ml.rl_envs.registry import available, get_env_class, make
from kairo_ml.rl_envs.transcript import Transcript, TranscriptEntry

__all__ = [
    "Action",
    "Done",
    "Info",
    "Observation",
    "RLEnvironment",
    "Reward",
    "ScoreReport",
    "Transcript",
    "TranscriptEntry",
    "available",
    "get_env_class",
    "make",
]
