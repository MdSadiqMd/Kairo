from __future__ import annotations

import json
from pathlib import Path

import pytest
from kairo_ml.evals.gate import evaluate_gate
from kairo_ml.evals.models import EvalSpec, PromotionGateSpec
from kairo_ml.evals.promotion import FileRegistryStore, PromotionError, promote, rollback
from kairo_ml.evals.report import build_report
from kairo_ml.evals.runners import SmokeRunner


def _smoke_spec(dataset: str) -> EvalSpec:
    return EvalSpec(
        id="smoke_v1",
        name="Smoke",
        type="mixed",
        dataset_uri=dataset,
        runner="smoke",
        scorer="contains",
        # Floor 0.0: this test exercises the runner+report, not the pass-rate
        # gate — with n=2 the Wilson CI is too wide to clear any real floor.
        promotion_gate=PromotionGateSpec(min_pass_rate=0.0, min_n=2, min_detectable_effect=0.0),
    )


def test_smoke_runner_scores_against_responder(tmp_path: Path) -> None:
    dataset = tmp_path / "d.jsonl"
    dataset.write_text(
        json.dumps({"id": "1", "prompt": "capital of France?", "expected": "Paris"})
        + "\n"
        + json.dumps({"id": "2", "prompt": "2+2?", "expected": "4", "scorer": "numeric"})
        + "\n"
    )
    answers = {"capital of France?": "The capital is Paris.", "2+2?": "4"}

    def responder(messages: list[dict]) -> tuple[str, float]:
        return answers[messages[-1]["content"]], 0.001

    run = SmokeRunner(responder).run(
        _smoke_spec(str(dataset)), model="m", model_version="v", router_url="http://x"
    )
    assert run.n == 2
    assert run.pass_rate == 1.0

    report = build_report(run, evaluate_gate(run, _smoke_spec(str(dataset)).promotion_gate))
    assert report["passed"] is True
    assert report["metrics"]["pass_rate"] == 1.0
    assert "cost_per_1k_requests" in report["metrics"]


def test_promotion_refuses_failed_report(tmp_path: Path) -> None:
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "models:\n"
        "  - name: model-32b\n    role: reasoner\n    version: v1\n"
        "    endpoint: http://x\n    served_model_id: s\n    max_model_len: 1024\n"
        "    deployable: true\n"
    )
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"eval_run_id": "e", "model_version": "v2", "passed": False}))
    store = FileRegistryStore(str(reg))
    with pytest.raises(PromotionError):
        promote(
            store,
            name="model-32b",
            role="reasoner",
            model_version="v2",
            eval_report_path=str(report),
        )


def test_promotion_and_rollback_update_registry(tmp_path: Path) -> None:
    reg = tmp_path / "registry.yaml"
    reg.write_text(
        "models:\n"
        "  - name: model-32b\n    role: reasoner\n    version: v1\n"
        "    endpoint: http://x\n    served_model_id: s\n    max_model_len: 1024\n"
        "    deployable: true\n"
    )
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"eval_run_id": "e", "model_version": "v2", "passed": True}))
    store = FileRegistryStore(str(reg))

    entry = promote(
        store, name="model-32b", role="reasoner", model_version="v2", eval_report_path=str(report)
    )
    assert entry["version"] == "v2" and entry["deployable"] is True

    back = rollback(store, name="model-32b", role="reasoner", to_version="v1")
    assert back["version"] == "v1"
