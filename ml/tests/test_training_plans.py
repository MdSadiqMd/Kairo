from __future__ import annotations

from kairo_ml.training.config import (
    CriticConfig,
    DistillationConfig,
    PreferenceConfig,
    QuantizationConfig,
    RewardModelConfig,
    SFTConfig,
    VerifierConfig,
)
from kairo_ml.training.critic import CriticTrainer
from kairo_ml.training.distillation import DistillationTrainer
from kairo_ml.training.mlflow_tracking import build_run_tags
from kairo_ml.training.preference import PreferenceTrainer
from kairo_ml.training.quantize import Quantizer
from kairo_ml.training.reward_model import RewardModelTrainer
from kairo_ml.training.sft import SFTTrainer
from kairo_ml.training.verifier import VerifierTrainer, format_verifier_examples

_COMMON = {
    "base_model": "MODEL_PROVIDER/Model-8B",
    "output_dir": "/out",
    "dataset_manifest_uri": "file:///m",
}


def test_sft_plan_long_cot_widens_seq_len() -> None:
    plan = SFTTrainer(SFTConfig(**_COMMON, long_cot=True, max_seq_len=4096)).plan()
    assert plan["job"] == "sft"
    assert plan["long_cot"] is True
    assert plan["max_seq_len"] == 8192  # widened for the reasoning trace
    assert plan["packing"] is False
    assert plan["lora"]["r"] == 16


def test_sft_plan_no_lora_when_disabled() -> None:
    plan = SFTTrainer(SFTConfig(**_COMMON, use_lora=False)).plan()
    assert plan["lora"] is None


def test_preference_plan_selects_method() -> None:
    plan = PreferenceTrainer(PreferenceConfig(**_COMMON, method="kto", beta=0.2)).plan()
    assert plan["method"] == "kto"
    assert plan["loss_type"] == "kto"
    assert plan["beta"] == 0.2


def test_reward_model_plan() -> None:
    plan = RewardModelTrainer(RewardModelConfig(**_COMMON)).plan()
    assert plan["objective"] == "pairwise_ranking"
    assert plan["num_labels"] == 1


def test_verifier_plan_binary_outcome() -> None:
    plan = VerifierTrainer(VerifierConfig(**_COMMON, label_field="inserted_bug_detected")).plan()
    assert plan["objective"] == "binary_outcome"
    assert plan["label_field"] == "inserted_bug_detected"
    assert plan["num_labels"] == 2


def test_verifier_formats_hidden_test_outcomes() -> None:
    records = [
        {"prompt": "solve", "output": "code A", "hidden_test_passed": True},
        {"prompt": "solve", "output": "code B", "hidden_test_passed": 0},
    ]
    examples = format_verifier_examples(records, label_field="hidden_test_passed")
    assert examples[0].label == 1
    assert examples[1].label == 0


def test_critic_plan() -> None:
    plan = CriticTrainer(CriticConfig(**_COMMON)).plan()
    assert plan["objective"] == "critique_sft"


def test_distillation_plan_records_teacher() -> None:
    plan = DistillationTrainer(
        DistillationConfig(**_COMMON, teacher_model="MODEL_PROVIDER/Model-235B")
    ).plan()
    assert plan["teacher_model"] == "MODEL_PROVIDER/Model-235B"
    assert plan["student_model"] == "MODEL_PROVIDER/Model-8B"


def test_quantize_plan_fp8_no_calibration() -> None:
    plan = Quantizer(QuantizationConfig(base_model="m", output_dir="/o", method="fp8")).plan()
    assert plan["requires_calibration"] is False
    assert "--scheme" in plan["command"]
    assert "FP8" in plan["command"]


def test_quantize_plan_awq_requires_calibration() -> None:
    cfg = QuantizationConfig(
        base_model="m",
        output_dir="/o",
        method="awq",
        calibration_dataset_uri="file:///cal",
        calibration_samples=256,
    )
    plan = Quantizer(cfg).plan()
    assert plan["requires_calibration"] is True
    assert "--calibration-dataset" in plan["command"]
    assert "256" in plan["command"]


def test_build_run_tags_includes_lineage() -> None:
    from kairo_ml.data.manifests import DatasetManifest

    manifest = DatasetManifest(
        dataset_id="sft_v1",
        created_at="2026-07-11T00:00:00Z",
        record_count=10,
        dedupe_hash="abc123",
        dp_epsilon=5.0,
    )
    tags = build_run_tags(manifest, git_commit="deadbeef", extra={"job": "sft"})
    assert tags["dataset_manifest_hash"] == "abc123"
    assert tags["git_commit"] == "deadbeef"
    assert tags["dp_epsilon"] == "5.0"
    assert tags["job"] == "sft"
