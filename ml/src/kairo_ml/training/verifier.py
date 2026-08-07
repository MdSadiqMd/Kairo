"""Verifier training

The verifier does objective scoring for code/math/tool outputs: it is trained
on outcomes that are ground truth, not preferences — did the hidden tests pass,
was an inserted bug detected. Each record carries a binary outcome in
config.label_field; the head learns to predict it from the model output

format_verifier_examples (pure, tested) turns raw records into labeled
examples; plan() resolves the binary-classification head; train() is the
only torch-touching method
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kairo_common import get_logger

from kairo_ml.training.config import VerifierConfig, base_plan
from kairo_ml.training.dataset import DatasetError, ensure_scanned, read_manifest

log = get_logger("verifier-trainer")


@dataclass(frozen=True)
class VerifierExample:
    prompt: str
    output: str
    label: int  # 1 = objectively correct (tests passed / bug caught), 0 = not


def format_verifier_examples(
    records: list[dict[str, Any]], *, label_field: str
) -> list[VerifierExample]:
    examples: list[VerifierExample] = []
    for rec in records:
        prompt = rec.get("prompt") or rec.get("instruction")
        output = rec.get("output") or rec.get("completion") or rec.get("response")
        if not isinstance(prompt, str) or not isinstance(output, str):
            raise DatasetError("verifier record needs string prompt and output fields")
        if label_field not in rec:
            raise DatasetError(f"verifier record missing outcome field {label_field!r}")
        label = int(bool(rec[label_field]))
        examples.append(VerifierExample(prompt=prompt, output=output, label=label))
    return examples


class VerifierTrainer:
    def __init__(
        self, config: VerifierConfig, *, records: list[dict[str, Any]] | None = None
    ) -> None:
        self.config = config
        self._records = records

    def plan(self) -> dict[str, Any]:
        plan = base_plan(self.config, "verifier")
        plan["objective"] = "binary_outcome"
        plan["label_field"] = self.config.label_field
        plan["num_labels"] = 2
        plan["max_seq_len"] = self.config.max_seq_len
        return plan

    def _load_examples(self) -> list[VerifierExample]:
        manifest = read_manifest(self.config.dataset_manifest_uri)
        ensure_scanned(manifest)
        if self._records is None:
            from kairo_ml.training.loaders import load_from_s3

            self._records = load_from_s3(manifest.samples_uri)
        return format_verifier_examples(self._records, label_field=self.config.label_field)

    def train(self) -> str:
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            Trainer,
            TrainingArguments,
        )

        plan = self.plan()
        examples = self._load_examples()
        tokenizer = AutoTokenizer.from_pretrained(self.config.base_model)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.base_model, num_labels=plan["num_labels"]
        )
        if plan["lora"]:
            model = get_peft_model(model, LoraConfig(**{**plan["lora"], "task_type": "SEQ_CLS"}))

        def _tokenize(row: dict[str, Any]) -> dict[str, Any]:
            enc = tokenizer(
                row["prompt"] + "\n" + row["output"],
                truncation=True,
                max_length=plan["max_seq_len"],
            )
            enc["labels"] = row["label"]
            return enc

        dataset = Dataset.from_list(
            [{"prompt": e.prompt, "output": e.output, "label": e.label} for e in examples]
        ).map(_tokenize)
        args = TrainingArguments(output_dir=self.config.output_dir, **plan["optim"])
        trainer = Trainer(model=model, args=args, train_dataset=dataset)
        trainer.train()
        trainer.save_model(self.config.output_dir)
        log.info("verifier training complete", extra={"output_dir": self.config.output_dir})
        return self.config.output_dir
