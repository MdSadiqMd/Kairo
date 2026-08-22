from __future__ import annotations

from pathlib import Path

import yaml
from kairo_ml.training.config import (
    DistillationConfig,
    PreferenceConfig,
    QuantizationConfig,
    SFTConfig,
    base_plan,
    resolve_lora,
    resolve_optim,
)


def test_sft_config_yaml_round_trip(tmp_path: Path) -> None:
    cfg = SFTConfig(
        base_model="MODEL_PROVIDER/Model-8B",
        output_dir="/out",
        dataset_manifest_uri="file:///m.json",
        long_cot=True,
        lr=1e-5,
        epochs=2.0,
    )
    path = tmp_path / "sft.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump()))
    loaded = SFTConfig.from_yaml(path)
    assert loaded == cfg
    assert loaded.long_cot is True
    assert loaded.use_lora is True  # LoRA default


def test_preference_config_defaults_and_round_trip(tmp_path: Path) -> None:
    cfg = PreferenceConfig(
        base_model="MODEL_PROVIDER/Model-8B",
        output_dir="/out",
        dataset_manifest_uri="file:///m.json",
        method="ipo",
    )
    path = tmp_path / "pref.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump()))
    loaded = PreferenceConfig.from_yaml(path)
    assert loaded.method == "ipo"
    assert loaded == cfg


def test_quantization_config_round_trip(tmp_path: Path) -> None:
    cfg = QuantizationConfig(base_model="MODEL_PROVIDER/Model-8B", output_dir="/out", method="awq")
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump()))
    assert QuantizationConfig.from_yaml(path) == cfg


def test_resolve_lora_off_returns_none() -> None:
    cfg = SFTConfig(
        base_model="m", output_dir="/o", dataset_manifest_uri="file:///m.json", use_lora=False
    )
    assert resolve_lora(cfg) is None


def test_resolve_lora_on_carries_params() -> None:
    cfg = SFTConfig(
        base_model="m", output_dir="/o", dataset_manifest_uri="file:///m.json", lora_r=8
    )
    lora = resolve_lora(cfg)
    assert lora is not None
    assert lora["r"] == 8
    assert lora["task_type"] == "CAUSAL_LM"


def test_resolve_optim_maps_fields() -> None:
    cfg = SFTConfig(
        base_model="m",
        output_dir="/o",
        dataset_manifest_uri="file:///m.json",
        epochs=3.0,
        lr=5e-5,
        per_device_batch_size=2,
        grad_accum=8,
    )
    optim = resolve_optim(cfg)
    assert optim["num_train_epochs"] == 3.0
    assert optim["learning_rate"] == 5e-5
    assert optim["per_device_train_batch_size"] == 2
    assert optim["gradient_accumulation_steps"] == 8


def test_base_plan_carries_dp_epsilon() -> None:
    cfg = DistillationConfig(
        base_model="student",
        output_dir="/o",
        dataset_manifest_uri="file:///m.json",
        teacher_model="teacher",
        dp_epsilon=5.0,
    )
    plan = base_plan(cfg, "distillation")
    assert plan["dp_epsilon"] == 5.0
    assert plan["job"] == "distillation"
