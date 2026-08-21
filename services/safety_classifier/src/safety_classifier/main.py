"""Safety classifier FastAPI service.

Three endpoints — input, output, and tool-action (autonomy) classification —
plus health and metrics. Stateless and cheap; runs on CPU or a small GPU.
The router calls /v1/classify/input before routing, the
streaming layer can call /v1/classify/output on completions, and the agent
runtime calls /v1/classify/action before risky tool actions.
"""

from __future__ import annotations

from fastapi import FastAPI, Response
from kairo_common import configure_logging, get_logger
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from safety_classifier.policy import (
    RuleAutonomyPolicy,
    RuleInputPolicy,
    RuleOutputPolicy,
)
from safety_classifier.schemas import (
    ActionRequest,
    ActionResponse,
    InputRequest,
    InputResponse,
    OutputRequest,
    OutputResponse,
)

log = get_logger(__name__)

DECISIONS = Counter("safety_decisions_total", "Safety decisions", ["endpoint", "decision"])


def _latest_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _full_text(messages: list[dict]) -> str:
    parts: list[str] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(p.get("text", "") for p in content if isinstance(p, dict))
    return "\n".join(parts)


def build_app() -> FastAPI:
    configure_logging("safety-classifier")
    app = FastAPI(title="Kairo safety classifier", version="0.1.0")
    input_policy = RuleInputPolicy()
    output_policy = RuleOutputPolicy()
    autonomy_policy = RuleAutonomyPolicy()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/classify/input")
    async def classify_input(req: InputRequest) -> InputResponse:
        v = input_policy.classify_input(
            latest_user_text=_latest_user_text(req.messages),
            full_text=_full_text(req.messages),
            has_tools=req.has_tools,
        )
        DECISIONS.labels(endpoint="input", decision=v.decision).inc()
        return InputResponse(decision=v.decision, task_type=v.task_type, reason=v.reason)

    @app.post("/v1/classify/output")
    async def classify_output(req: OutputRequest) -> OutputResponse:
        v = output_policy.classify_output(text=req.text)
        DECISIONS.labels(endpoint="output", decision=v.decision).inc()
        return OutputResponse(decision=v.decision, reason=v.reason, redactions=v.redactions)

    @app.post("/v1/classify/action")
    async def classify_action(req: ActionRequest) -> ActionResponse:
        v = autonomy_policy.classify_action(action=req.action, target=req.target)
        DECISIONS.labels(endpoint="action", decision=v.decision).inc()
        return ActionResponse(
            decision=v.decision,
            risk_level=v.risk_level,
            reason=v.reason,
            safer_alternative=v.safer_alternative,
        )

    return app


app = build_app()


def run() -> None:
    import uvicorn

    uvicorn.run("safety_classifier.main:app", host="0.0.0.0", port=8080)
