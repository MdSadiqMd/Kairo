"""Distillation trainer

Transfers large-reasoner behavior into a smaller student by SFT on teacher
traces: the student is fine-tuned to reproduce the teacher's (prompt ->
completion) outputs. `plan()` records the teacher and KD temperature with no
torch; `train()` lazily runs the SFT loop over the distilled traces
"""

from __future__ import annotations

from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import DistillationConfig, base_plan
from kairo_ml.training.dataset import SFTExample, ensure_scanned, prepare_sft, read_manifest

log = get_logger("distillation-trainer")


class DistillationTrainer:
    def __init__(
        self, config: DistillationConfig, *, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "distillation")
        plan["objective"] = "trace_sft"
        plan["teacher_model"] = self.config.teacher_model
        plan["student_model"] = self.config.base_model
        plan["kd_temperature"] = self.config.kd_temperature
        plan["max_seq_len"] = self.config.max_seq_len
        return plan

    def _load_examples(self) -> list[SFTExample]:
        manifest = read_manifest(self.config.dataset_manifest_uri)
        ensure_scanned(manifest)
        if self._records is None:
            from kairo_ml.training.loaders import load_from_s3

            self._records = load_from_s3(manifest.samples_uri)
        return prepare_sft(manifest, self._records)

    def train(self) -> str:
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig as TrlSFTConfig
        from trl import SFTTrainer as TrlSFTTrainer

        plan = self.plan()
        examples = self._load_examples()
        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        model = AutoModelForCausalLM.from_pretrained(self.config.base_model)
        peft_config = LoraConfig(**plan["lora"]) if plan["lora"] else None
        dataset = Dataset.from_list(
            [{"prompt": e.prompt, "completion": e.completion} for e in examples]
        )
        trl_args = TrlSFTConfig(
            output_dir=self.config.output_dir,
            max_length=plan["max_seq_len"],
            **plan["optim"],
        )
        trainer = TrlSFTTrainer(
            model=model,
            args=trl_args,
            train_dataset=dataset,
            processing_class=tokenizer,
            peft_config=peft_config,
        )
        trainer.train()
        trainer.save_model(self.config.output_dir)
        log.info(
            "distillation complete",
            extra={"teacher": self.config.teacher_model, "output_dir": self.config.output_dir},
        )
        return self.config.output_dir
