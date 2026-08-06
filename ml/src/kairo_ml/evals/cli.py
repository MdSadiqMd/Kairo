"""Eval / promotion CLI

    kairo-eval run --suite smoke_v1 --model model-30b-a3b-dev \
        --model-version 2026-07-11-001 --router-url https://... [--out report.json]
    kairo-eval promote --name model-32b --role reasoner \
        --model-version 2026-07-11-001 --report report.json [--registry-file ...]
    kairo-eval rollback --name model-32b --role reasoner --to-version 2026-07-10-002

`scripts/run_eval_suite.py` / `promote_model.py` / `rollback_model.py` are
thin wrappers over these subcommands
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kairo_common import configure_logging, get_logger

from kairo_ml.evals.gate import evaluate_gate
from kairo_ml.evals.promotion import FileRegistryStore, PromotionError, promote, rollback
from kairo_ml.evals.registry import EvalRegistry
from kairo_ml.evals.report import build_report
from kairo_ml.evals.runners import CodeRepairRunner, SmokeRunner

log = get_logger("kairo-eval")


def _get_runner(spec, router_url: str, model: str, api_key: str | None):
    """Select the appropriate runner based on the suite's runner field."""
    runner_type = getattr(spec, "runner", "smoke")
    if runner_type == "code_repair":
        return CodeRepairRunner.for_router(router_url, model, api_key=api_key)
    return SmokeRunner.for_router(router_url, model, api_key=api_key)


def _cmd_run(args: argparse.Namespace) -> int:
    registry = EvalRegistry.load(args.registry)
    spec = registry.get(args.suite)
    runner = _get_runner(spec, args.router_url, args.model, args.api_key)
    run = runner.run(
        spec, model=args.model, model_version=args.model_version, router_url=args.router_url
    )
    decision = evaluate_gate(run, spec.promotion_gate)

    from kairo_ml.proofs.settings import zk_enabled

    zk_fields: dict = {}
    if zk_enabled():
        import os

        from kairo_ml.proofs import witness
        from kairo_ml.proofs.jobs import DirProofJobSink, SqsProofJobSink

        queue_url = os.environ.get("PROOF_QUEUE_URL", "")
        artifacts_uri = os.environ.get("PROOF_ARTIFACTS_URI", "")
        if queue_url:
            sink = SqsProofJobSink(queue_url, artifacts_uri)
        else:
            proof_dir = os.environ.get("PROOF_QUEUE_DIR", "/tmp/proof-jobs")
            sink = DirProofJobSink(proof_dir)
        zk_fields = witness.commit_eval_run(run, decision, spec.promotion_gate, sink=sink) or {}

    report = build_report(run, decision)
    report.update(zk_fields)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(decision.summary(), file=sys.stderr)
    return 0 if decision.promotable else 1


def _cmd_promote(args: argparse.Namespace) -> int:
    store = FileRegistryStore(args.registry_file)
    try:
        entry = promote(
            store,
            name=args.name,
            role=args.role,
            model_version=args.model_version,
            eval_report_path=args.report,
        )
    except PromotionError as exc:
        log.error("promotion refused", extra={"reason": str(exc)})
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"PROMOTED {entry['name']} ({entry['role']}) -> {entry['version']}")
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    store = FileRegistryStore(args.registry_file)
    try:
        entry = rollback(store, name=args.name, role=args.role, to_version=args.to_version)
    except PromotionError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"ROLLED BACK {entry['name']} ({entry['role']}) -> {entry['version']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kairo-eval", description="Eval and promotion CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run an eval suite against a served model")
    run.add_argument("--suite", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--model-version", required=True)
    run.add_argument("--router-url", required=True)
    run.add_argument("--api-key", default=None)
    run.add_argument("--registry", default="ml/evals/registry")
    run.add_argument("--out", default=None)
    run.set_defaults(func=_cmd_run)

    prom = sub.add_parser("promote", help="Promote a model version if its eval passed")
    prom.add_argument("--name", required=True)
    prom.add_argument("--role", required=True)
    prom.add_argument("--model-version", required=True)
    prom.add_argument("--report", required=True)
    prom.add_argument("--registry-file", default="ml/models/registry.local.yaml")
    prom.set_defaults(func=_cmd_promote)

    rb = sub.add_parser("rollback", help="Roll a role back to a prior version")
    rb.add_argument("--name", required=True)
    rb.add_argument("--role", required=True)
    rb.add_argument("--to-version", required=True)
    rb.add_argument("--registry-file", default="ml/models/registry.local.yaml")
    rb.set_defaults(func=_cmd_rollback)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging("kairo-eval")
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
