"""Training-job configs

Every job type is a pydantic model loadable from YAML. `BaseTrainConfig` holds
the fields common to all fine-tuning jobs; per-job configs add only what they
need. Defaults encode two plan decisions:

- `use_lora=True` — prefer LoRA/adapters over full fine-tuning for
  production-derived data, which memorizes less.
- `dp_epsilon=None` — DP-SGD is off unless a sensitive-class dataset opts in,
  and the chosen ε is recorded in the dataset manifest.

The `resolve_*` / `base_plan` helpers turn a config into the pure-python
argument dict every trainer's `plan()` returns, so the resolved training
arguments are testable without torch
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel

PreferenceMethod = Literal["dpo", "ipo", "kto"]
QuantMethod = Literal["fp8", "awq"]


class BaseTrainConfig(BaseModel):
    base_model: str
    output_dir: str
    dataset_manifest_uri: str
    use_lora: bool = True
    use_qlora: bool = True  # 4-bit quantized base + LoRA (QLoRA)
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    seed: int = 42
    epochs: float = 1.0
    lr: float = 2e-4
    per_device_batch_size: int = 1
    grad_accum: int = 16
    gradient_checkpointing: bool = True  # trade compute for memory
    dp_epsilon: float | None = None
    mlflow_run_name: str | None = None
    deepspeed_config: str | None = None  # path to ZeRO-3 config if enabled

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)


class SFTConfig(BaseTrainConfig):
    max_seq_len: int = 4096
    long_cot: bool = False  # reasoning cold-start; keeps long chains of thought


class PreferenceConfig(BaseTrainConfig):
    method: PreferenceMethod = "dpo"
    beta: float = 0.1
    max_seq_len: int = 4096


class RewardModelConfig(BaseTrainConfig):
    max_seq_len: int = 4096
    num_labels: int = 1  # scalar preference/quality head


class VerifierConfig(BaseTrainConfig):
    max_seq_len: int = 4096
    # The verifier trains on objective outcomes: did hidden tests pass, was an
    # inserted bug detected. `label_field` names the outcome column.
    label_field: str = "hidden_test_passed"


class CriticConfig(BaseTrainConfig):
    max_seq_len: int = 4096


class DistillationConfig(BaseTrainConfig):
    teacher_model: str
    max_seq_len: int = 4096
    kd_temperature: float = 1.0


class QuantizationConfig(BaseModel):
    """No training loop — produces a deployment artifact."""

    base_model: str
    output_dir: str
    method: QuantMethod = "fp8"
    calibration_dataset_uri: str | None = None
    calibration_samples: int = 512

    @classmethod
    def from_yaml(cls, path: str | Path) -> Self:
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)


def resolve_bnb_config(cfg: BaseTrainConfig) -> dict[str, Any] | None:
    """BitsAndBytes 4-bit config for QLoRA. Returns None if QLoRA disabled."""
    if not cfg.use_qlora:
        return None
    return {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",  # normalized float 4-bit (best for LLMs)
        "bnb_4bit_compute_dtype": "bfloat16",  # compute in bf16, store in 4-bit
        "bnb_4bit_use_double_quant": True,  # nested quantization for extra savings
    }


def resolve_lora(cfg: BaseTrainConfig) -> dict[str, Any] | None:
    if not cfg.use_lora:
        return None
    return {
        "r": cfg.lora_r,
        "lora_alpha": cfg.lora_alpha,
        "lora_dropout": cfg.lora_dropout,
        "bias": "none",
        "task_type": "CAUSAL_LM",
    }


def resolve_optim(cfg: BaseTrainConfig) -> dict[str, Any]:
    return {
        "num_train_epochs": cfg.epochs,
        "learning_rate": cfg.lr,
        "per_device_train_batch_size": cfg.per_device_batch_size,
        "gradient_accumulation_steps": cfg.grad_accum,
        "seed": cfg.seed,
    }


def base_plan(cfg: BaseTrainConfig, job: str) -> dict[str, Any]:
    return {
        "job": job,
        "base_model": cfg.base_model,
        "output_dir": cfg.output_dir,
        "dataset_manifest_uri": cfg.dataset_manifest_uri,
        "seed": cfg.seed,
        "use_lora": cfg.use_lora,
        "use_qlora": cfg.use_qlora,
        "lora": resolve_lora(cfg),
        "bnb_config": resolve_bnb_config(cfg),
        "optim": resolve_optim(cfg),
        "gradient_checkpointing": cfg.gradient_checkpointing,
        "dp_epsilon": cfg.dp_epsilon,
        "mlflow_run_name": cfg.mlflow_run_name,
        "deepspeed_config": cfg.deepspeed_config,
    }
