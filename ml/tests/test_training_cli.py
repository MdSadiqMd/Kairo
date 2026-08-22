from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from kairo_ml.training.cli import main


def _write_config(tmp_path: Path, data: dict[str, object]) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return str(path)


def test_dry_run_sft_exits_zero_and_prints_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _write_config(
        tmp_path,
        {
            "base_model": "MODEL_PROVIDER/Model-8B",
            "output_dir": "/out",
            "dataset_manifest_uri": "file:///m.json",
            "long_cot": True,
        },
    )
    rc = main(["sft", "--config", config, "--dry-run"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["job"] == "sft"
    assert plan["long_cot"] is True


def test_dry_run_quantize_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _write_config(tmp_path, {"base_model": "m", "output_dir": "/o", "method": "awq"})
    rc = main(["quantize", "--config", config, "--dry-run"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["method"] == "awq"


def test_unknown_job_rejected_by_argparse(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {})
    with pytest.raises(SystemExit):
        main(["nonsense", "--config", config, "--dry-run"])
