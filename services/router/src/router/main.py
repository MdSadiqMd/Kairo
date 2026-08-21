"""FastAPI application — the only public entry point.

Wires config, registry, auth, quota, safety, upstream, verifier, and event sink
into a RouterService and exposes the OpenAI-compatible surface plus health
and metrics. Endpoints are thin; all logic lives in pipeline.py so it is
unit-testable without a server.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from kairo_common import PlatformError, configure_logging, get_logger
from kairo_common.ids import REQUEST_ID_HEADER, coerce_request_id
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from router.auth import Authenticator
from router.config import Settings, get_settings
from router.model_registry import ModelRegistry, build_loader
from router.pipeline import RouterService
from router.quota import QuotaManager
from router.safety import SafetyClient
from router.schemas import ChatCompletionRequest, ModelCard, ModelList
from router.telemetry import build_event_sink
from router.upstream import UpstreamClient
from router.verifier import VerifierClient

log = get_logger(__name__)


class AppState:
    settings: Settings
    service: RouterService
    registry: ModelRegistry
    authenticator: Authenticator
    loader: Any
    http: httpx.AsyncClient


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging("router", settings.log_level)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        limits = httpx.Limits(max_connections=settings.upstream_max_connections)
        timeout = httpx.Timeout(
            connect=settings.upstream_connect_timeout_s,
            read=settings.upstream_read_timeout_s,
            write=settings.upstream_read_timeout_s,
            pool=settings.upstream_connect_timeout_s,
        )
        http = httpx.AsyncClient(limits=limits, timeout=timeout)
        loader = build_loader(
            settings.registry_backend,
            file=settings.registry_file,
            table=settings.registry_table,
        )
        registry = ModelRegistry(loader.load_entries(), settings.registry_refresh_seconds)
        state = AppState()
        state.settings = settings
        state.http = http
        state.loader = loader
        state.registry = registry
        state.authenticator = Authenticator.from_file(
            settings.api_keys_file, enabled=settings.auth_enabled
        )
        state.service = RouterService(
            settings=settings,
            registry=registry,
            quota=QuotaManager(),
            safety=SafetyClient(
                enabled=settings.safety_enabled,
                url=settings.safety_url,
                client=http,
                timeout_s=settings.safety_timeout_s,
                fail_open=settings.safety_fail_open,
            ),
            upstream=UpstreamClient(http),
            verifier=VerifierClient(http),
            event_sink=build_event_sink(settings.events_backend, settings.events_stream),
        )
        app.state.ctx = state
        try:
            yield
        finally:
            await http.aclose()

    app = FastAPI(title="Kairo router", version="0.1.0", lifespan=lifespan)
    _register_routes(app)
    _register_error_handlers(app)
    return app


def _register_routes(app: FastAPI) -> None:
    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> Response:
        state: AppState = request.app.state.ctx
        state.registry.maybe_refresh(state.loader)
        if not state.registry.list_public():
            return JSONResponse({"status": "no models"}, status_code=503)
        return JSONResponse({"status": "ready"})

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/v1/models")
    async def list_models(request: Request) -> ModelList:
        state: AppState = request.app.state.ctx
        state.registry.maybe_refresh(state.loader)
        return ModelList(data=[ModelCard(id=e.name) for e in state.registry.list_public()])

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        body: ChatCompletionRequest,
        authorization: str | None = Header(default=None),
        x_request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
    ) -> Response:
        state: AppState = request.app.state.ctx
        request_id = coerce_request_id(x_request_id)
        tenant = state.authenticator.authenticate(authorization)
        state.registry.maybe_refresh(state.loader)

        prep = await state.service.prepare(body, tenant, request_id)

        if body.stream:

            async def gen() -> AsyncIterator[bytes]:
                async for chunk in state.service.stream(prep):
                    yield chunk

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={REQUEST_ID_HEADER: request_id, "Cache-Control": "no-cache"},
            )

        response = await state.service.complete(prep, body)
        return JSONResponse(response, headers={REQUEST_ID_HEADER: request_id})


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(PlatformError)
    async def handle_platform_error(request: Request, exc: PlatformError) -> Response:
        log.info(
            "request rejected",
            extra={"error_code": exc.code.value, "retriable": exc.retriable, **exc.details},
        )
        return JSONResponse(exc.to_openai_error(), status_code=exc.http_status)


app = build_app()


def run() -> None:  # console-script entry point
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "router.main:app",
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level.lower(),
    )
