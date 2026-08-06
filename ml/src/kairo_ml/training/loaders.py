"""S3 dataset loaders

Loads JSONL datasets from S3 or local filesystem. Respects `AWS_ENDPOINT_URL`
environment variable for local development with MiniStack/LocalStack.

Requires the aws` extra: `pip install kairo-ml[aws]`
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kairo_common import get_logger

log = get_logger("s3-loader")


def load_from_s3(uri: str) -> list[dict]:
    """Load a JSONL file from S3 or local filesystem.

    Supports:
    - s3://bucket/key - S3 URIs (uses boto3)
    - file:///path or /path - local filesystem paths

    For S3, respects AWS_ENDPOINT_URL env var for local development with
    MiniStack or LocalStack. Large files are streamed line-by-line to avoid
    loading the entire file into memory.

    Returns:
        List of parsed JSON records from the JSONL file.
    """
    if uri.startswith("s3://"):
        return _load_s3_jsonl(uri)
    path = uri.removeprefix("file://")
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _load_s3_jsonl(uri: str) -> list[dict]:
    """Load JSONL from S3 using boto3 with streaming."""
    try:
        import boto3
    except ImportError as e:
        raise ImportError(
            "boto3 is required for S3 loading. Install with: pip install kairo-ml[aws]"
        ) from e

    parts = uri.removeprefix("s3://").split("/", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid S3 URI: {uri}")
    bucket, key = parts

    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    client_kwargs = {}
    if endpoint_url:
        log.debug("using custom endpoint", extra={"endpoint_url": endpoint_url})
        client_kwargs["endpoint_url"] = endpoint_url

    s3 = boto3.client("s3", **client_kwargs)
    log.info("loading dataset from s3", extra={"bucket": bucket, "key": key})

    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"]

    records: list[dict] = []
    for line in body.iter_lines():
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if line:
            records.append(json.loads(line))

    log.info("loaded records from s3", extra={"count": len(records)})
    return records


def load_manifest_samples(manifest_samples_uri: str) -> list[dict]:
    """Load samples from a manifest's samples_uri

    This is a convenience wrapper around load_from_s3 for use in trainers
    that need to load samples referenced by a manifest

    Args:
        manifest_samples_uri: The samples_uri from a dataset manifest

    Returns:
        List of parsed JSON records
    """
    return load_from_s3(manifest_samples_uri)
