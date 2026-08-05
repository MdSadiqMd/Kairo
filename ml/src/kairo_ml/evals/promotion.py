"""Model promotion and rollback

Promotion flips a candidate version to `deployable` in the model registry —
but only if its eval report passed the gate. This is the code path behind
`scripts/promote_model.py`. The registry backend mirrors the router's
(file for dev, DynamoDB for prod) so a promoted version is exactly what the
router will serve.

Rollback re-points a role to a prior known-good version. At the model layer the
fast path is a router traffic flip to a warm blue-green standby; this
function handles the registry-state half of that flip
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import yaml


class PromotionError(RuntimeError):
    pass


class RegistryStore(Protocol):
    def load(self) -> list[dict[str, Any]]: ...
    def save(self, models: list[dict[str, Any]]) -> None: ...


class FileRegistryStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        data = yaml.safe_load(self.path.read_text()) or {}
        return data.get("models", [])

    def save(self, models: list[dict[str, Any]]) -> None:
        self.path.write_text(yaml.safe_dump({"models": models}, sort_keys=False))


def _gate_passed(report_path: str) -> tuple[bool, dict[str, Any]]:
    report = json.loads(Path(report_path).read_text())
    return bool(report.get("passed")), report


def promote(
    store: RegistryStore,
    *,
    name: str,
    role: str,
    model_version: str,
    eval_report_path: str,
) -> dict[str, Any]:
    """Mark (name, role) deployable at ``model_version`` iff the report passed.

    Refuses to promote on a failed or mismatched report — the gate is not
    advisory.
    """
    passed, report = _gate_passed(eval_report_path)
    if not passed:
        raise PromotionError(
            f"eval report {report.get('eval_run_id')} did not pass the gate; refusing to promote"
        )
    if report.get("model_version") not in (None, model_version):
        raise PromotionError(f"report is for {report.get('model_version')}, not {model_version}")

    models = store.load()
    updated: dict[str, Any] | None = None
    for m in models:
        if m.get("name") == name and m.get("role") == role:
            m["version"] = model_version
            m["deployable"] = True
            updated = m
        elif m.get("role") == role:
            # Demote the previously-promoted version for this role.
            m["deployable"] = m.get("name") == name
    if updated is None:
        raise PromotionError(f"no registry entry for name={name} role={role}")
    store.save(models)
    return updated


def rollback(store: RegistryStore, *, name: str, role: str, to_version: str) -> dict[str, Any]:
    """Re-point (name, role) to a prior version and mark it deployable."""
    models = store.load()
    target: dict[str, Any] | None = None
    for m in models:
        if m.get("name") == name and m.get("role") == role:
            m["version"] = to_version
            m["deployable"] = True
            target = m
    if target is None:
        raise PromotionError(f"no registry entry for name={name} role={role}")
    store.save(models)
    return target
