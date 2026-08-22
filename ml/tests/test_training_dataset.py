from __future__ import annotations

import json
from pathlib import Path

import pytest
from kairo_ml.data.manifests import DatasetManifest
from kairo_ml.training.dataset import (
    DatasetError,
    UnscannedManifestError,
    ensure_scanned,
    format_preference_examples,
    format_sft_examples,
    load_records,
    prepare_sft,
    read_manifest,
)


def _manifest(**overrides: object) -> DatasetManifest:
    data: dict[str, object] = {
        "dataset_id": "sft_v1",
        "created_at": "2026-07-11T00:00:00Z",
        "record_count": 2,
    }
    data.update(overrides)
    return DatasetManifest.model_validate(data)


def test_ensure_scanned_passes_clean_manifest() -> None:
    ensure_scanned(_manifest())  # does not raise


def test_ensure_scanned_refuses_failed_pii_scan() -> None:
    with pytest.raises(UnscannedManifestError, match="pii_scan"):
        ensure_scanned(_manifest(pii_scan="failed"))


def test_ensure_scanned_refuses_pending_license_scan() -> None:
    with pytest.raises(UnscannedManifestError, match="license_scan"):
        ensure_scanned(_manifest(license_scan="pending"))


def test_read_manifest_from_local_json(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(_manifest().model_dump_json())
    loaded = read_manifest(str(path))
    assert loaded.dataset_id == "sft_v1"


def test_read_manifest_refuses_s3() -> None:
    with pytest.raises(DatasetError, match="aws extra"):
        read_manifest("s3://bucket/manifest.json")


def test_format_sft_examples() -> None:
    records = [
        {"prompt": "p1", "completion": "c1"},
        {"instruction": "p2", "response": "c2", "reasoning": "think"},
    ]
    examples = format_sft_examples(records)
    assert examples[0].prompt == "p1"
    assert examples[0].completion == "c1"
    assert examples[1].prompt == "p2"
    assert examples[1].long_cot is True


def test_format_sft_rejects_missing_fields() -> None:
    with pytest.raises(DatasetError):
        format_sft_examples([{"prompt": "only prompt"}])


def test_format_preference_examples() -> None:
    records = [{"prompt": "p", "chosen": "good", "rejected": "bad"}]
    examples = format_preference_examples(records)
    assert examples[0].chosen == "good"
    assert examples[0].rejected == "bad"


def test_prepare_sft_refuses_unscanned_before_formatting() -> None:
    # Even with valid records, an unscanned manifest blocks the whole build.
    with pytest.raises(UnscannedManifestError):
        prepare_sft(_manifest(pii_scan="failed"), [{"prompt": "p", "completion": "c"}])


def test_load_records_ndjson(tmp_path: Path) -> None:
    path = tmp_path / "records.ndjson"
    path.write_text(
        json.dumps({"prompt": "a", "completion": "b"})
        + "\n\n"
        + json.dumps({"prompt": "c", "completion": "d"})
        + "\n"
    )
    records = load_records(str(path))
    assert len(records) == 2
    assert records[0]["prompt"] == "a"
