"""Adapter artifact management for online RL

Handles versioning, manifests, and S3 upload/download for LoRA adapters produced
by online policy updates
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class AdapterManifest:
    """Metadata for a trained LoRA adapter checkpoint"""

    adapter_id: str
    base_model_id: str
    policy_version: int
    trainer: str  # "lora", "qlora", "online-dpo", "rloo"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    parent_adapter_id: str | None = None
    dataset_manifest_uri: str | None = None
    artifact_uri: str | None = None
    git_sha: str | None = None
    passed_gate: bool = False
    training_config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdapterManifest:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def get_git_sha() -> str | None:
    """Get current git SHA, or None if not in a repo"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).parent,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def write_adapter_manifest(manifest: AdapterManifest, output_dir: str | Path) -> Path:
    """Write adapter manifest JSON alongside the weights"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    manifest_path = output_path / "adapter_manifest.json"
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
    return manifest_path


def read_adapter_manifest(manifest_path: str | Path) -> AdapterManifest:
    """Read adapter manifest from file"""
    data = json.loads(Path(manifest_path).read_text())
    return AdapterManifest.from_dict(data)


def _get_s3_client():
    """Get boto3 S3 client, respecting AWS_ENDPOINT_URL for LocalStack"""
    import boto3

    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    return boto3.client("s3", endpoint_url=endpoint_url)


def upload_adapter_to_s3(local_dir: str | Path, s3_uri: str) -> str:
    """Upload adapter directory to S3

    Args:
        local_dir: Local directory containing adapter files (adapter_model.safetensors, etc.)
        s3_uri: S3 URI like s3://bucket/path/to/adapter

    Returns:
        The s3_uri that was uploaded to
    """
    local_path = Path(local_dir)
    if not local_path.exists():
        raise FileNotFoundError(f"Local directory not found: {local_dir}")

    bucket, prefix = s3_uri.removeprefix("s3://").split("/", 1)
    s3 = _get_s3_client()

    for file_path in local_path.rglob("*"):
        if file_path.is_file():
            rel_path = file_path.relative_to(local_path)
            key = f"{prefix}/{rel_path}"
            s3.upload_file(str(file_path), bucket, key)

    return s3_uri


def download_adapter_from_s3(s3_uri: str, local_dir: str | Path) -> Path:
    """Download adapter from S3 to local directory

    Args:
        s3_uri: S3 URI like s3://bucket/path/to/adapter
        local_dir: Local directory to download to

    Returns:
        Path to the local directory
    """
    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)

    bucket, prefix = s3_uri.removeprefix("s3://").split("/", 1)
    s3 = _get_s3_client()

    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel_path = key.removeprefix(prefix).lstrip("/")
            if rel_path:
                local_file = local_path / rel_path
                local_file.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(local_file))

    return local_path
