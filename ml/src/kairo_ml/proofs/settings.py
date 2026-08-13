from __future__ import annotations

import functools
import os


@functools.cache
def zk_enabled() -> bool:
    # In-cluster: qctl always injects ZK_INFERENCE from config/models.json
    # Bare processes (pytest, direct runs): missing env -> false, keeping tests
    # hermetic without AWS. The config-level default-true is honored because
    # deployed pods always receive the explicit env var
    return os.environ.get("ZK_INFERENCE", "false").lower() == "true"
