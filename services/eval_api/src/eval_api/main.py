"""Eval registry + promotion-gate API.

Serves the versioned eval registry and evaluates promotion gates on submitted
eval runs. CI (eval-candidate.yml) and the eval-runner Job POST an
EvalRun (optionally with a baseline run) and receive the statistical gate
decision — the single authority on whether a model may ship.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Response
from kairo_common import configure_logging, get_logger
from kairo_ml.evals.gate import evaluate_gate
from kairo_ml.evals.models import EvalRun, EvalSpec
from kairo_ml.evals.registry import EvalRegistry
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel

log = get_logger(__name__)

GATE_DECISIONS = Counter("eval_gate_decisions_total", "Gate decisions", ["suite", "result"])


class GateRequest(BaseModel):
    suite: str
    candidate: EvalRun
    baseline: EvalRun | None = None


class GateCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class GateResponse(BaseModel):
    promotable: bool
    checks: list[GateCheck]


def build_app(registry_dir: str = "ml/evals/registry") -> FastAPI:
    configure_logging("eval-api")
    app = FastAPI(title="Kairo eval API", version="0.1.0")
    registry = EvalRegistry.load(registry_dir)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/evals")
    async def list_evals() -> dict[str, list[str]]:
        return {"suites": registry.ids()}

    @app.get("/v1/evals/{suite_id}")
    async def get_eval(suite_id: str) -> EvalSpec:
        try:
            return registry.get(suite_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/gate/evaluate")
    async def evaluate(req: GateRequest) -> GateResponse:
        try:
            spec = registry.get(req.suite)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        decision = evaluate_gate(req.candidate, spec.promotion_gate, baseline=req.baseline)
        GATE_DECISIONS.labels(
            suite=req.suite, result="promotable" if decision.promotable else "blocked"
        ).inc()
        return GateResponse(
            promotable=decision.promotable,
            checks=[
                GateCheck(name=c.name, passed=c.passed, detail=c.detail) for c in decision.checks
            ],
        )

    return app


app = build_app()


def run() -> None:
    import uvicorn

    uvicorn.run("eval_api.main:app", host="0.0.0.0", port=8080)
