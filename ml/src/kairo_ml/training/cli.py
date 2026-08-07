"""Training CLI

    kairo-train <job> --config c.yaml [--dry-run]

--dry-run loads the config, builds the trainer, prints the resolved plan as
JSON, and exits 0 — fully offline, no torch. Without --dry-run the job's
`train()` / `run()` runs, which lazily imports the heavy ML stack.

Jobs: sft, preference, reward_model, verifier, critic, distillation, quantize.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from kairo_common import configure_logging, get_logger

from kairo_ml.training.config import (
    CriticConfig,
    DistillationConfig,
    PreferenceConfig,
    QuantizationConfig,
    RewardModelConfig,
    SFTConfig,
    VerifierConfig,
)

log = get_logger("kairo-train")

# Each job maps to (config loader, plan builder, runner). The plan builder is
# pure python (no torch) so --dry-run works offline; the runner touches torch.
JOBS = ("sft", "preference", "reward_model", "verifier", "critic", "distillation", "quantize")


def _make_trainer(job: str, config_path: str) -> Any:
    """Construct the trainer for `job`. Trainer modules are import-safe with
    no torch installed (heavy deps are lazy inside train()/run()), so importing
    them all here keeps dispatch to a single lookup."""
    from kairo_ml.training.critic import CriticTrainer
    from kairo_ml.training.distillation import DistillationTrainer
    from kairo_ml.training.preference import PreferenceTrainer
    from kairo_ml.training.quantize import Quantizer
    from kairo_ml.training.reward_model import RewardModelTrainer
    from kairo_ml.training.sft import SFTTrainer
    from kairo_ml.training.verifier import VerifierTrainer

    factories: dict[str, Callable[[], Any]] = {
        "sft": lambda: SFTTrainer(SFTConfig.from_yaml(config_path)),
        "preference": lambda: PreferenceTrainer(PreferenceConfig.from_yaml(config_path)),
        "reward_model": lambda: RewardModelTrainer(RewardModelConfig.from_yaml(config_path)),
        "verifier": lambda: VerifierTrainer(VerifierConfig.from_yaml(config_path)),
        "critic": lambda: CriticTrainer(CriticConfig.from_yaml(config_path)),
        "distillation": lambda: DistillationTrainer(DistillationConfig.from_yaml(config_path)),
        "quantize": lambda: Quantizer(QuantizationConfig.from_yaml(config_path)),
    }
    try:
        return factories[job]()
    except KeyError:
        raise ValueError(f"unknown job {job!r}") from None


def _build_plan(job: str, config_path: str) -> dict[str, Any]:
    plan: dict[str, Any] = _make_trainer(job, config_path).plan()
    return plan


def _run_job(job: str, config_path: str, mlflow_run_name: str | None = None) -> str:
    import os

    from kairo_ml.training.mlflow_tracking import MLflowTracker

    trainer = _make_trainer(job, config_path)
    plan = trainer.plan()

    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
    experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME", f"kairo-{job}")
    run_name = (
        mlflow_run_name
        or plan.get("mlflow_run_name")
        or f"{job}-{plan.get('base_model', 'unknown')}"
    )

    tracker = MLflowTracker(run_name, tracking_uri=tracking_uri, experiment=experiment)
    with tracker:
        tracker.log_params({k: v for k, v in plan.items() if not isinstance(v, dict)})
        runner = getattr(trainer, "run", None) or trainer.train
        output: str = runner()
        tracker.log_artifact(output)
        tracker.log_metrics({"completed": 1.0})

    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kairo-train", description="Training job CLI")
    parser.add_argument("job", choices=JOBS)
    parser.add_argument("--config", required=True, help="Path to the job's YAML config")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved training plan and exit without training",
    )
    parser.add_argument(
        "--mlflow-run-name",
        default=None,
        help="Override MLflow run name (env: MLFLOW_TRACKING_URI enables tracking)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging("kairo-train")
    args = build_parser().parse_args(argv)
    if args.dry_run:
        plan = _build_plan(args.job, args.config)
        print(json.dumps(plan, indent=2, default=str))
        return 0
    output = _run_job(args.job, args.config, getattr(args, "mlflow_run_name", None))
    log.info("training job finished", extra={"job": args.job, "output": output})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
