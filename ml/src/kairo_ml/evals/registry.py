"""Eval registry loader.

Loads versioned eval specs from ``ml/evals/registry/*.yaml``. The registry is
the source of truth for what a suite measures and what its promotion gate
requires — nothing gates on ad-hoc thresholds.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kairo_ml.evals.models import EvalSpec

DEFAULT_REGISTRY_DIR = Path("ml/evals/registry")


class EvalRegistry:
    def __init__(self, specs: dict[str, EvalSpec]) -> None:
        self._specs = specs

    @classmethod
    def load(cls, directory: str | Path = DEFAULT_REGISTRY_DIR) -> EvalRegistry:
        directory = Path(directory)
        specs: dict[str, EvalSpec] = {}
        for path in sorted(directory.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            spec = EvalSpec(**data)
            specs[spec.id] = spec
        return cls(specs)

    def get(self, suite_id: str) -> EvalSpec:
        if suite_id not in self._specs:
            raise KeyError(f"unknown eval suite: {suite_id}")
        return self._specs[suite_id]

    def ids(self) -> list[str]:
        return list(self._specs)
