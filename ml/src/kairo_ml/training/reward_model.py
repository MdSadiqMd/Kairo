"""Reward-model training

Trains a scalar scoring head on preference pairs: the model learns to rank a
chosen completion above a rejected one. `plan()` resolves the sequence-
classification head + LoRA/optim args with no torch; `train()` lazily runs
trl's `RewardTrainer`
"""

from __future__ import annotations

from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import RewardModelConfig, base_plan
from kairo_ml.training.dataset import (
    PreferenceExample,
    ensure_scanned,
    prepare_preference,
    read_manifest,
)

log = get_logger("reward-model-trainer")


class RewardModelTrainer:
    def __init__(
        self, config: RewardModelConfig, *, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "reward_model")
        plan["objective"] = "pairwise_ranking"
        plan["num_labels"] = self.config.num_labels
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
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from trl import RewardConfig, RewardTrainer

        plan = self.plan()
        examples = self._load_examples()
        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.base_model, num_labels=plan["num_labels"]
        )
        peft_config = None
        if plan["lora"]:
            peft_config = LoraConfig(**{**plan["lora"], "task_type": "SEQ_CLS"})
        dataset = Dataset.from_list(
            [{"chosen": e.prompt + e.chosen, "rejected": e.prompt + e.rejected} for e in examples]
        )
        reward_args = RewardConfig(
            output_dir=self.config.output_dir,
            max_length=plan["max_seq_len"],
            **plan["optim"],
        )
        trainer = RewardTrainer(
            model=model,
            args=reward_args,
            train_dataset=dataset,
            processing_class=tokenizer,
            peft_config=peft_config,
        )
        trainer.train()
        trainer.save_model(self.config.output_dir)
        log.info("reward-model training complete", extra={"output_dir": self.config.output_dir})
        return self.config.output_dir
