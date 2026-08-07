"""SFT / Long-CoT SFT trainer

LoRA/QLoRA fine-tuning via peft + trl. The class splits into:
- plan() — resolves the full training-argument dict from the config. Pure
  python, no torch, unit-tested
- train() — the only torch-touching method; lazily imports transformers /
  peft / trl and runs the actual loop

Long-CoT SFT (reasoning cold start) is the same trainer with
long_cot=True, which widens the sequence budget so full chains of thought
survive truncation
"""

from __future__ import annotations

from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import SFTConfig, base_plan
from kairo_ml.training.dataset import SFTExample, ensure_scanned, prepare_sft, read_manifest

log = get_logger("sft-trainer")


class SFTTrainer:
    def __init__(self, config: SFTConfig, *, records: list[dict[str, Any]] | None = None) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "sft")
        # Long-CoT keeps the reasoning trace intact; a truncated chain teaches the
        # model to stop thinking early, defeating the cold-start
        seq_len = self.config.max_seq_len
        if self.config.long_cot:
            seq_len = max(seq_len, 8192)
        plan["long_cot"] = self.config.long_cot
        plan["max_seq_len"] = seq_len
        plan["packing"] = not self.config.long_cot
        return plan

    def _load_examples(self) -> list[SFTExample]:
        manifest = read_manifest(self.config.dataset_manifest_uri)
        ensure_scanned(manifest)
        if self._records is None:
            from kairo_ml.training.loaders import load_from_s3

            self._records = load_from_s3(manifest.samples_uri)
        return prepare_sft(manifest, self._records)

    def train(self) -> str:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, prepare_model_for_kbit_training
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        from trl import SFTConfig as TrlSFTConfig
        from trl import SFTTrainer as TrlSFTTrainer

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
            [{"prompt": e.prompt, "completion": e.completion} for e in examples]
        )

        trl_kwargs: dict = {
            "output_dir": self.config.output_dir,
            "max_length": plan["max_seq_len"],
            "packing": plan["packing"],
            "gradient_checkpointing": plan["gradient_checkpointing"],
            **plan["optim"],
        }
        if plan["deepspeed_config"]:
            trl_kwargs["deepspeed"] = plan["deepspeed_config"]

        trl_args = TrlSFTConfig(**trl_kwargs)
        trainer = TrlSFTTrainer(
            model=model,
            args=trl_args,
            train_dataset=dataset,
            processing_class=tokenizer,
            peft_config=peft_config,
        )
        trainer.train()
        trainer.save_model(self.config.output_dir)
        log.info("sft training complete", extra={"output_dir": self.config.output_dir})
        return self.config.output_dir
