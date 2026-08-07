"""MLflow tracking for training runs

Every training run logs parameters and metrics, and tags the run with the
dataset manifest hash and the git commit so a checkpoint's exact lineage
is recoverable (right-to-delete). Tag assembly is a pure function
(build_run_tags) so it is unit-testable without mlflow

The MLflowTracker imports mlflow lazily and degrades to a logging no-op when
mlflow is not installed, so training code paths run in the offline dev venv
"""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from types import TracebackType
from typing import Any

from kairo_common import get_logger

from kairo_ml.data.manifests import DatasetManifest

log = get_logger("mlflow-tracking")


def current_git_commit(default: str = "unknown") -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return default
    return out.stdout.strip() or default


def build_run_tags(
    manifest: DatasetManifest,
    *,
    git_commit: str,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Assemble the MLflow tags that pin a run to its data and code lineage."""
    tags: dict[str, str] = {
        "dataset_id": manifest.dataset_id,
        "dataset_manifest_hash": manifest.dedupe_hash,
        "consent_policy": manifest.consent_policy,
        "git_commit": git_commit,
    }
    if manifest.dp_epsilon is not None:
        tags["dp_epsilon"] = str(manifest.dp_epsilon)
    if extra:
        tags.update({k: str(v) for k, v in extra.items()})
    return tags


class MLflowTracker:
    """Thin MLflow wrapper with a no-op fallback when mlflow is absent."""

    def __init__(
        self,
        run_name: str | None,
        *,
        tracking_uri: str | None = None,
        experiment: str | None = None,
    ) -> None:
        self.run_name = run_name
        self.tracking_uri = tracking_uri
        self.experiment = experiment
        self._mlflow: Any | None = None
        self._active = False

    def __enter__(self) -> MLflowTracker:
        try:
            import mlflow
        except ImportError:
            log.info("mlflow not installed; tracking is a no-op", extra={"run": self.run_name})
            return self
        self._mlflow = mlflow
        if self.tracking_uri:
            mlflow.set_tracking_uri(self.tracking_uri)
        if self.experiment:
            mlflow.set_experiment(self.experiment)
        mlflow.start_run(run_name=self.run_name)
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._mlflow is not None and self._active:
            self._mlflow.end_run(status="FAILED" if exc_type else "FINISHED")

    def log_params(self, params: Mapping[str, Any]) -> None:
        if self._mlflow is not None:
            self._mlflow.log_params(dict(params))
        else:
            log.debug("log_params (no-op)", extra={"count": len(params)})

    def log_metrics(self, metrics: Mapping[str, float], *, step: int | None = None) -> None:
        if self._mlflow is not None:
            self._mlflow.log_metrics(dict(metrics), step=step)
        else:
            log.debug("log_metrics (no-op)", extra={"count": len(metrics)})

    def set_tags(self, tags: Mapping[str, str]) -> None:
        if self._mlflow is not None:
            self._mlflow.set_tags(dict(tags))
        else:
            log.debug("set_tags (no-op)", extra={"count": len(tags)})

    def log_artifact(self, local_path: str) -> None:
        if self._mlflow is not None:
            self._mlflow.log_artifact(local_path)
        else:
            log.debug("log_artifact (no-op)", extra={"path": local_path})
