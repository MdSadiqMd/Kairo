"""Dataset loading and formatting for training

Two responsibilities, both pure-python and torch-free:

1. Refuse to train on unscanned data. A `DatasetManifest` whose
   `pii_scan` or `license_scan` is not `"passed"` raises before any record
   is read — "what never enters the corpus can never be memorized". This
   is a hard gate, not a warning.
2. Format raw records into the SFT (prompt/completion) and preference
   (chosen/rejected) shapes the trainers consume.

Record I/O is pluggable: `read_manifest` reads a local JSON/YAML manifest for
dev and tests; production wires an S3 reader via the aws extra. Formatting works
on already-loaded dicts so it is fully unit-testable offline
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from kairo_ml.data.manifests import DatasetManifest


class DatasetError(ValueError):
    """A record or manifest is unusable for training."""


class UnscannedManifestError(DatasetError):
    """The manifest has not passed the required privacy/license scans."""


@dataclass(frozen=True)
class SFTExample:
    prompt: str
    completion: str
    long_cot: bool = False


@dataclass(frozen=True)
class PreferenceExample:
    prompt: str
    chosen: str
    rejected: str


def read_manifest(uri: str) -> DatasetManifest:
    """Load a manifest from a local path or ``file://`` URI (dev/tests)."""
    if uri.startswith("s3://"):
        raise DatasetError(
            "remote manifest loading requires the aws extra; pass a local path in dev"
        )
    path = uri[len("file://") :] if uri.startswith("file://") else uri
    text = Path(path).read_text()
    data = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    return DatasetManifest.model_validate(data)


def ensure_scanned(manifest: DatasetManifest) -> None:
    """Raise unless privacy and license scans both passed.

    Called before any record is loaded so unscanned data can never reach a
    training loop.
    """
    problems: list[str] = []
    if manifest.pii_scan != "passed":
        problems.append(f"pii_scan={manifest.pii_scan!r}")
    if manifest.license_scan != "passed":
        problems.append(f"license_scan={manifest.license_scan!r}")
    if problems:
        raise UnscannedManifestError(
            f"dataset {manifest.dataset_id!r} is not trainable: {', '.join(problems)} "
            f"(both must be 'passed')"
        )


def to_sft_example(record: dict[str, Any]) -> SFTExample:
    prompt = record.get("prompt") or record.get("instruction")
    completion = record.get("completion") or record.get("response") or record.get("output")
    if not isinstance(prompt, str) or not isinstance(completion, str):
        raise DatasetError("SFT record needs string prompt and completion fields")
    return SFTExample(prompt=prompt, completion=completion, long_cot=bool(record.get("reasoning")))


def to_preference_example(record: dict[str, Any]) -> PreferenceExample:
    prompt = record.get("prompt") or record.get("instruction")
    chosen = record.get("chosen")
    rejected = record.get("rejected")
    if not (isinstance(prompt, str) and isinstance(chosen, str) and isinstance(rejected, str)):
        raise DatasetError("preference record needs string prompt, chosen and rejected fields")
    return PreferenceExample(prompt=prompt, chosen=chosen, rejected=rejected)


def format_sft_examples(records: list[dict[str, Any]]) -> list[SFTExample]:
    return [to_sft_example(r) for r in records]


def format_preference_examples(records: list[dict[str, Any]]) -> list[PreferenceExample]:
    return [to_preference_example(r) for r in records]


def prepare_sft(manifest: DatasetManifest, records: list[dict[str, Any]]) -> list[SFTExample]:
    ensure_scanned(manifest)
    return format_sft_examples(records)


def prepare_preference(
    manifest: DatasetManifest, records: list[dict[str, Any]]
) -> list[PreferenceExample]:
    ensure_scanned(manifest)
    return format_preference_examples(records)


def load_records(uri: str) -> list[dict[str, Any]]:
    """Read training records from a local NDJSON/JSON file (dev/tests)."""
    if uri.startswith("s3://"):
        raise DatasetError("remote record loading requires the aws extra")
    path = uri[len("file://") :] if uri.startswith("file://") else uri
    text = Path(path).read_text()
    if path.endswith(".json"):
        data = json.loads(text)
        if not isinstance(data, list):
            raise DatasetError("JSON record file must contain a list of objects")
        return [dict(r) for r in data]
    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            records.append(json.loads(line))
    return records
