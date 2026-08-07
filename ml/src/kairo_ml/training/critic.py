"""Critic training

The critic finds bugs and critiques answers. It is trained SFT-style on
(problem+answer -> critique) traces, where the target is a natural-language
critique that identifies flaws. `plan()` resolves the generative critique
objective with no torch; `train()` lazily runs the SFT loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import CriticConfig, base_plan
from kairo_ml.training.dataset import DatasetError, ensure_scanned, read_manifest

log = get_logger("critic-trainer")


@dataclass(frozen=True)
class CritiqueExample:
    prompt: str  # problem + candidate answer
    critique: str  # target critique identifying flaws


def format_critique_examples(records: list[dict[str, Any]]) -> list[CritiqueExample]:
    examples: list[CritiqueExample] = []
    for rec in records:
        prompt = rec.get("prompt") or rec.get("answer") or rec.get("instruction")
        critique = rec.get("critique") or rec.get("completion") or rec.get("response")
        if not isinstance(prompt, str) or not isinstance(critique, str):
            raise DatasetError("critic record needs string prompt and critique fields")
        examples.append(CritiqueExample(prompt=prompt, critique=critique))
    return examples


class CriticTrainer:
    def __init__(
        self, config: CriticConfig, *, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "critic")
        plan["objective"] = "critique_sft"
        plan["max_seq_len"] = self.config.max_seq_len
        return plan

    def _load_examples(self) -> list[CritiqueExample]:
        manifest = read_manifest(self.config.dataset_manifest_uri)
        ensure_scanned(manifest)
        if self._records is None:
            from kairo_ml.training.loaders import load_from_s3

            self._records = load_from_s3(manifest.samples_uri)
        return format_critique_examples(self._records)

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
            [{"prompt": e.prompt, "completion": e.critique} for e in examples]
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
        log.info("critic training complete", extra={"output_dir": self.config.output_dir})
        return self.config.output_dir
