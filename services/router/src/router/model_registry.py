"""Model registry — endpoint lookup and deployable-version resolution.

The registry answers two questions: (1) for a logical model name (e.g.
model-32b) and a route tier (fast/reasoner/verifier/safety), which upstream
service should we call; and (2) what is the currently promoted version for
that role — a model reaches production only after passing the eval gate,
so the router always serves the promoted version, never a raw guess.

Two backends: a YAML file for local dev, and DynamoDB in production. The
production path is behind the dynamodb build of load_entries; the file
backend keeps the router runnable with zero AWS dependencies.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import yaml
from kairo_common import get_logger, model_unavailable
from pydantic import BaseModel, ConfigDict

log = get_logger(__name__)


class ModelEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str  # logical name exposed to clients, e.g. "model-32b"
    role: str  # "fast" | "reasoner" | "verifier" | "safety"
    version: str  # promoted version tag, e.g. "2026-07-11-001"
    endpoint: str  # internal cluster URL of the vLLM/SGLang service
    served_model_id: str  # the id vLLM answers to (its --served-model-name)
    max_model_len: int
    replicas: int = 1
    precision: str = "fp8"
    deployable: bool = True  # False until the promotion gate passes
    policy_version: int = 0  # bumped by online-RL promotion; stamped on events


class ModelRegistry:
    """Thread-safe, periodically-refreshed view of promoted models."""

    def __init__(self, entries: list[ModelEntry], refresh_seconds: int = 30) -> None:
        self._lock = threading.RLock()
        self._by_name: dict[str, ModelEntry] = {}
        self._by_role: dict[str, ModelEntry] = {}
        self._refresh_seconds = refresh_seconds
        self._loaded_at = 0.0
        self._set(entries)

    def _set(self, entries: list[ModelEntry]) -> None:
        by_name: dict[str, ModelEntry] = {}
        by_role: dict[str, ModelEntry] = {}
        for e in entries:
            if not e.deployable:
                continue
            by_name[e.name] = e
            # First deployable entry per role wins as the default for that tier.
            by_role.setdefault(e.role, e)
        with self._lock:
            self._by_name = by_name
            self._by_role = by_role
            self._loaded_at = time.monotonic()

    def resolve(self, *, name: str | None, role: str) -> ModelEntry:
        """Resolve to a concrete deployable entry.

        An explicit, valid client model name wins; otherwise fall back to the
        promoted default for the requested role.
        """
        with self._lock:
            if name and name in self._by_name:
                return self._by_name[name]
            if role in self._by_role:
                return self._by_role[role]
        raise model_unavailable(
            f"no deployable model for name={name!r} role={role!r}",
            requested=name,
            role=role,
        )

    def list_public(self) -> list[ModelEntry]:
        with self._lock:
            return list(self._by_name.values())

    def maybe_refresh(self, loader: RegistryLoader) -> None:
        with self._lock:
            fresh = time.monotonic() - self._loaded_at < self._refresh_seconds
        if fresh:
            return
        try:
            self._set(loader.load_entries())
        except Exception:  # never let a refresh failure take down serving
            log.warning("registry refresh failed; serving last-known", exc_info=True)


class RegistryLoader:
    def load_entries(self) -> list[ModelEntry]:  # pragma: no cover - interface
        raise NotImplementedError


class FileRegistryLoader(RegistryLoader):
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load_entries(self) -> list[ModelEntry]:
        if not self.path.exists():
            raise model_unavailable(f"registry file not found: {self.path}")
        raw: dict[str, Any] = yaml.safe_load(self.path.read_text()) or {}
        return [ModelEntry(**item) for item in raw.get("models", [])]


def build_loader(backend: str, *, file: str, table: str) -> RegistryLoader:
    if backend == "file":
        return FileRegistryLoader(file)
    from router.registry_dynamodb import DynamoRegistryLoader

    return DynamoRegistryLoader(table)
