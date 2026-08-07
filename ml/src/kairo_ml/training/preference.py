"""Preference optimization: DPO / IPO / KTO

Same plan() / train() split as SFT. plan() resolves the method-specific
loss and the shared LoRA/optim args with no torch; train() lazily imports trl
and runs the chosen preference loss over (prompt, chosen, rejected) pairs
"""

from __future__ import annotations

from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import PreferenceConfig, base_plan
from kairo_ml.training.dataset import (
    PreferenceExample,
    ensure_scanned,
    prepare_preference,
    read_manifest,
)

log = get_logger("preference-trainer")


class PreferenceTrainer:
    def __init__(
        self, config: PreferenceConfig, *, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "preference")
        plan["method"] = self.config.method
        plan["loss_type"] = self.config.method  # trl DPOTrainer selects IPO/KTO by loss_type
        plan["beta"] = self.config.beta
        plan["max_seq_len"] = self.config.max_seq_len
        return plan

    def _load_examples(self) -> list[PreferenceExample]:
        manifest = read_manifest(self.config.dataset_manifest_uri)
        ensure_scanned(manifest)
        if self._records is None:
            from kairo_ml.training.loaders import load_from_s3

            self._records = load_from_s3(manifest.samples_uri)
        return prepare_preference(manifest, self._records)

    def train(self) -> str:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import DPOConfig, DPOTrainer

        plan = self.plan()
        examples = self._load_examples()
        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)

        model_kwargs: dict = {"torch_dtype": torch.bfloat16}
        if plan["bnb_config"]:
            model_kwargs["quantization_config"] = BitsAndBytesConfig(**plan["bnb_config"])
            log.info("QLoRA enabled: base model loaded in 4-bit NF4")

        model = AutoModelForCausalLM.from_pretrained(self.config.base_model, **model_kwargs)

        if plan["bnb_config"]:
            model = prepare_model_for_kbit_training(
                model, use_gradient_checkpointing=plan["gradient_checkpointing"]
            )

        peft_config = LoraConfig(**plan["lora"]) if plan["lora"] else None
        dataset = Dataset.from_list(
            [{"prompt": e.prompt, "chosen": e.chosen, "rejected": e.rejected} for e in examples]
        )

        dpo_kwargs: dict = {
            "output_dir": self.config.output_dir,
            "beta": plan["beta"],
            "loss_type": plan["loss_type"],
            "max_length": plan["max_seq_len"],
            "gradient_checkpointing": plan["gradient_checkpointing"],
            **plan["optim"],
        }
        if plan["deepspeed_config"]:
            dpo_kwargs["deepspeed"] = plan["deepspeed_config"]

        dpo_args = DPOConfig(**dpo_kwargs)
        trainer = DPOTrainer(
            model=model,
            args=dpo_args,
            train_dataset=dataset,
            processing_class=tokenizer,
            peft_config=peft_config,
        )
        trainer.train()
        trainer.save_model(self.config.output_dir)
        log.info(
            "preference training complete",
            extra={"method": self.config.method, "output_dir": self.config.output_dir},
        )
        return self.config.output_dir
