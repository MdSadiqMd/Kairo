"""Policy updaters for online RL

Provides:
- ArtifactOnlyPolicyUpdater: Debug-only, writes JSON with rollout data
- LoRAPolicyUpdater: Real adapter training via TRL/PEFT
- get_policy_updater(): Factory function for env-based selection
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from kairo_common import get_logger

from kairo_ml.rl.artifacts import (
    AdapterManifest,
    get_git_sha,
    upload_adapter_to_s3,
    write_adapter_manifest,
)
from kairo_ml.rl.online_loop import PolicyUpdater, Rollout

log = get_logger("policy-updaters")


@dataclass
class LoRAConfig:
    """Configuration for LoRA/QLoRA training"""

    base_model: str
    output_dir: str
    use_qlora: bool = True
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list[str] = field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"]
    )
    lr: float = 2e-5
    max_steps: int = 1
    per_device_batch_size: int = 1
    gradient_accumulation_steps: int = 1
    max_seq_length: int = 2048
    trainer_type: Literal["rloo", "online-dpo"] = "rloo"
    parent_adapter_id: str | None = None
    policy_version: int = 0
    # S3 URI for adapter backup; if set, uploads after training.
    adapter_s3_uri: str | None = None
    # Local PVC path for vLLM to load; if set, copies adapter after training.
    adapter_pvc_path: str | None = None


class ArtifactOnlyPolicyUpdater(PolicyUpdater):
    """Debug-only updater that writes JSON without training

    Useful for testing the online RL loop without GPU resources
    """

    def __init__(self, output_uri: str) -> None:
        self.output_uri = output_uri

    def apply_update(self, advantages: Sequence[float], rollouts: Sequence[Rollout]) -> None:
        payload = {
            "created_at": int(time.time()),
            "kind": "online-rl-candidate",
            "rollouts": [asdict(r) for r in rollouts],
            "advantages": list(advantages),
        }
        self._write_json(payload)

    def _write_json(self, payload: dict) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True).encode()
        if self.output_uri.startswith("s3://"):
            import boto3

            endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
            bucket, key = self.output_uri.removeprefix("s3://").split("/", 1)
            boto3.client("s3", endpoint_url=endpoint_url).put_object(
                Bucket=bucket, Key=key, Body=data
            )
            return
        path = Path(self.output_uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


class LoRAPolicyUpdater(PolicyUpdater):
    """Real LoRA/QLoRA adapter training via TRL

    Produces adapter_model.safetensors and writes an adapter manifest
    Works in prod (CUDA) and local (CPU with tiny model)
    """

    def __init__(self, config: LoRAConfig) -> None:
        self.config = config

    def apply_update(self, advantages: Sequence[float], rollouts: Sequence[Rollout]) -> None:
        if not rollouts:
            log.warning("No rollouts to train on")
            return

        if self.config.trainer_type == "rloo":
            self._train_rloo(advantages, rollouts)
        else:
            self._train_online_dpo(rollouts)

    def _train_rloo(self, advantages: Sequence[float], rollouts: Sequence[Rollout]) -> None:
        """RLOO-style training with explicit advantages"""
        import torch
        from datasets import Dataset
        from peft import LoraConfig as PeftLoraConfig
        from peft import get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig, SFTTrainer

        output_path = Path(self.config.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_kwargs: dict[str, Any] = {
            "torch_dtype": torch.bfloat16 if device == "cuda" else torch.float32
        }

        if self.config.use_qlora and device == "cuda":
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
            log.info("QLoRA enabled: loading base model in 4-bit NF4")

        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            device_map="auto" if device == "cuda" else None,
            **model_kwargs,
        )

        if self.config.use_qlora and device == "cuda":
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

        peft_config = PeftLoraConfig(
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.target_modules,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, peft_config)

        training_data = self._prepare_weighted_sft_data(advantages, rollouts)
        if not training_data:
            log.warning("No valid training samples after filtering")
            return

        dataset = Dataset.from_list(training_data)

        training_args = SFTConfig(
            output_dir=str(output_path),
            max_steps=self.config.max_steps,
            per_device_train_batch_size=self.config.per_device_batch_size,
            gradient_accumulation_steps=self.config.gradient_accumulation_steps,
            learning_rate=self.config.lr,
            max_length=self.config.max_seq_length,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
            use_cpu=device == "cpu",
            optim="adamw_torch" if device == "cpu" else "adamw_torch_fused",
        )

        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=dataset,
            processing_class=tokenizer,
        )
        trainer.train()

        model.save_pretrained(output_path)
        tokenizer.save_pretrained(output_path)

        self._write_manifest(trainer_type="rloo")
        self._upload_and_copy(output_path)
        log.info("RLOO training complete", extra={"output_dir": str(output_path)})

    def _train_online_dpo(self, rollouts: Sequence[Rollout]) -> None:
        """Online DPO training from preference pairs"""
        import torch
        from datasets import Dataset
        from peft import LoraConfig as PeftLoraConfig
        from peft import get_peft_model, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import DPOConfig, DPOTrainer

        from kairo_ml.rl.dataset_builder import build_preference_pairs, to_trl_dpo_format

        output_path = Path(self.config.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        pairs = build_preference_pairs(rollouts)
        if not pairs:
            log.warning("No preference pairs generated from rollouts")
            return

        dpo_data = to_trl_dpo_format(pairs)
        if not dpo_data:
            log.warning("No valid DPO training data")
            return

        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_kwargs: dict[str, Any] = {
            "torch_dtype": torch.bfloat16 if device == "cuda" else torch.float32
        }

        if self.config.use_qlora and device == "cuda":
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
            log.info("QLoRA enabled for DPO: loading base model in 4-bit NF4")

        model = AutoModelForCausalLM.from_pretrained(
            self.config.base_model,
            device_map="auto" if device == "cuda" else None,
            **model_kwargs,
        )
        ref_model = None  # DPOTrainer creates implicit reference

        if self.config.use_qlora and device == "cuda":
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

        peft_config = PeftLoraConfig(
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.target_modules,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, peft_config)

        dataset = Dataset.from_list(dpo_data)

        training_args = DPOConfig(
            output_dir=str(output_path),
            max_steps=self.config.max_steps,
            per_device_train_batch_size=self.config.per_device_batch_size,
            gradient_accumulation_steps=self.config.gradient_accumulation_steps,
            learning_rate=self.config.lr,
            max_length=self.config.max_seq_length,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
        )

        trainer = DPOTrainer(
            model=model,
            ref_model=ref_model,
            args=training_args,
            train_dataset=dataset,
            processing_class=tokenizer,
        )
        trainer.train()

        model.save_pretrained(output_path)
        tokenizer.save_pretrained(output_path)

        self._write_manifest(trainer_type="online-dpo")
        self._upload_and_copy(output_path)
        log.info("Online DPO training complete", extra={"output_dir": str(output_path)})

    def _prepare_weighted_sft_data(
        self, advantages: Sequence[float], rollouts: Sequence[Rollout]
    ) -> list[dict]:
        """Prepare data for advantage-weighted SFT (simplified RLOO)

        Filters to positive-advantage samples and formats for SFT training
        The prompt_raw is JSON-serialized messages; output_raw is the assistant response
        """
        data = []
        for adv, rollout in zip(advantages, rollouts, strict=True):
            if adv <= 0:
                continue

            prompt = rollout.prompt_raw
            completion = rollout.output_raw

            if prompt and completion:
                data.append(
                    {
                        "text": f"{prompt}\n\nAssistant: {completion}",
                    }
                )
        return data

    def _write_manifest(self, trainer_type: str) -> None:
        """Write adapter manifest alongside weights"""
        adapter_id = f"adapter-{uuid.uuid4().hex[:8]}"
        manifest = AdapterManifest(
            adapter_id=adapter_id,
            base_model_id=self.config.base_model,
            parent_adapter_id=self.config.parent_adapter_id,
            policy_version=self.config.policy_version,
            trainer=trainer_type,
            git_sha=get_git_sha(),
            training_config={
                "lora_r": self.config.lora_r,
                "lora_alpha": self.config.lora_alpha,
                "lora_dropout": self.config.lora_dropout,
                "use_qlora": self.config.use_qlora,
                "lr": self.config.lr,
                "max_steps": self.config.max_steps,
            },
        )
        write_adapter_manifest(manifest, self.config.output_dir)

    def _upload_and_copy(self, output_path: Path) -> None:
        """Upload adapter to S3 and copy to PVC if configured"""
        import shutil

        if self.config.adapter_s3_uri:
            try:
                upload_adapter_to_s3(output_path, self.config.adapter_s3_uri)
                log.info("Adapter uploaded to S3", extra={"uri": self.config.adapter_s3_uri})
            except Exception:
                log.exception("Failed to upload adapter to S3")

        if self.config.adapter_pvc_path:
            try:
                pvc_path = Path(self.config.adapter_pvc_path)
                if pvc_path.exists():
                    shutil.rmtree(pvc_path)
                shutil.copytree(output_path, pvc_path)
                log.info("Adapter copied to PVC", extra={"path": str(pvc_path)})
            except Exception:
                log.exception("Failed to copy adapter to PVC")


def get_policy_updater(
    updater_type: str | None = None,
    *,
    output_uri: str = "",
    lora_config: LoRAConfig | None = None,
) -> PolicyUpdater:
    """Factory function for policy updaters

    Args:
        updater_type: "artifact-only" or "lora". If None, reads from ONLINE_RL_UPDATER env var
        output_uri: Output URI for artifact-only mode
        lora_config: Configuration for LoRA training

    Returns:
        Configured PolicyUpdater instance
    """
    if updater_type is None:
        updater_type = os.environ.get("ONLINE_RL_UPDATER", "artifact-only")

    if updater_type == "artifact-only":
        if not output_uri:
            output_uri = os.environ.get("ONLINE_RL_OUTPUT_URI", "/tmp/online-rl/candidate.json")
        return ArtifactOnlyPolicyUpdater(output_uri)

    elif updater_type == "lora":
        if lora_config is None:
            lora_config = lora_config_from_env()
        return LoRAPolicyUpdater(lora_config)

    else:
        raise ValueError(f"Unknown updater type: {updater_type}")


def lora_config_from_env() -> LoRAConfig:
    """Build LoRAConfig from environment variables."""
    return LoRAConfig(
        base_model=os.environ.get("ONLINE_RL_BASE_MODEL", "Qwen/Qwen2.5-0.5B"),
        output_dir=os.environ.get("ONLINE_RL_OUTPUT_DIR", "/tmp/online-rl/adapter"),
        use_qlora=os.environ.get("ONLINE_RL_USE_QLORA", "true").lower() == "true",
        lora_r=int(os.environ.get("ONLINE_RL_LORA_R", "16")),
        lora_alpha=int(os.environ.get("ONLINE_RL_LORA_ALPHA", "32")),
        lora_dropout=float(os.environ.get("ONLINE_RL_LORA_DROPOUT", "0.05")),
        lr=float(os.environ.get("ONLINE_RL_LR", "2e-5")),
        max_steps=int(os.environ.get("ONLINE_RL_MAX_STEPS", "1")),
        per_device_batch_size=int(os.environ.get("ONLINE_RL_BATCH_SIZE", "1")),
        max_seq_length=int(os.environ.get("ONLINE_RL_MAX_SEQ_LEN", "2048")),
        trainer_type=os.environ.get("ONLINE_RL_TRAINER_TYPE", "rloo"),  # type: ignore
        policy_version=int(os.environ.get("ONLINE_RL_POLICY_STEP", "0")),
        adapter_s3_uri=os.environ.get("ONLINE_RL_ADAPTER_S3_URI"),
        adapter_pvc_path=os.environ.get("ONLINE_RL_ADAPTER_PVC_PATH"),
    )
