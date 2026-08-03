"""Isolated execution sandbox

Shared contract for RL environments, the strict coding eval harness, and the
agent runtime. `base` defines the protocol; `local` is the filesystem +
subprocess implementation used everywhere offline
"""

from kairo_ml.sandbox.base import RunResult, Sandbox
from kairo_ml.sandbox.local import LocalSandbox

__all__ = ["LocalSandbox", "RunResult", "Sandbox"]
