"""Checkpoint stores for hibernate/resume.

Checkpointing lets a long-running agent snapshot its combined workflow +
machine state, hibernate, and resume later (or after a crash) without redoing
work. The CheckpointStore protocol keeps callers backend-agnostic:
LocalCheckpointStore is the offline/test default; S3CheckpointStore is
the production backend and lazily imports boto3 so the default import path
stays dependency-free
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, unquote

from kairo_common import get_logger

logger = get_logger(__name__)


class CheckpointStore(Protocol):
    def save(self, checkpoint_id: str, payload: dict[str, Any]) -> None: ...

    def load(self, checkpoint_id: str) -> dict[str, Any] | None: ...

    def list_ids(self) -> list[str]: ...


class LocalCheckpointStore:
    """Filesystem checkpoint store. Checkpoint ids are percent-encoded so ids
    containing / or : (e.g. run:step) map to safe flat filenames"""

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)

    def _path(self, checkpoint_id: str) -> Path:
        return self._dir / f"{quote(checkpoint_id, safe='')}.json"

    def save(self, checkpoint_id: str, payload: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(checkpoint_id).write_text(json.dumps(payload, default=str), encoding="utf-8")

    def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        path = self._path(checkpoint_id)
        if not path.exists():
            return None
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def list_ids(self) -> list[str]:
        if not self._dir.exists():
            return []
        return sorted(unquote(p.stem) for p in self._dir.glob("*.json"))


class S3CheckpointStore:
    """S3-backed checkpoint store (production). boto3 is imported
    lazily and an injected client is honored so tests never touch AWS"""

    def __init__(self, bucket: str, prefix: str = "", *, client: Any | None = None) -> None:
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3")
        return self._client

    def _key(self, checkpoint_id: str) -> str:
        safe = quote(checkpoint_id, safe="")
        return f"{self._prefix}/{safe}.json" if self._prefix else f"{safe}.json"

    def save(self, checkpoint_id: str, payload: dict[str, Any]) -> None:
        client = self._get_client()
        client.put_object(
            Bucket=self._bucket,
            Key=self._key(checkpoint_id),
            Body=json.dumps(payload, default=str).encode("utf-8"),
        )

    def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        client = self._get_client()
        try:
            response = client.get_object(Bucket=self._bucket, Key=self._key(checkpoint_id))
        except client.exceptions.NoSuchKey:
            return None
        loaded: dict[str, Any] = json.loads(response["Body"].read().decode("utf-8"))
        return loaded

    def list_ids(self) -> list[str]:
        client = self._get_client()
        prefix = f"{self._prefix}/" if self._prefix else ""
        paginator = client.get_paginator("list_objects_v2")
        ids: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                stem = Path(obj["Key"]).stem
                ids.append(unquote(stem))
        return sorted(ids)
