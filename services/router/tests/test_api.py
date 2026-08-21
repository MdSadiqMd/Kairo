from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager
from router.config import Settings
from router.main import build_app

UPSTREAM = "http://vllm-test.local:8000"


@pytest.fixture
def registry_file(tmp_path: Path) -> str:
    path = tmp_path / "registry.yaml"
    path.write_text(
        "models:\n"
        "  - name: model-8b\n"
        "    role: fast\n"
        "    version: v1\n"
        f"    endpoint: {UPSTREAM}\n"
        "    served_model_id: MODEL_PROVIDER/Model-8B\n"
        "    max_model_len: 32768\n"
        "    deployable: true\n"
        "  - name: model-32b\n"
        "    role: reasoner\n"
        "    version: v1\n"
        f"    endpoint: {UPSTREAM}\n"
        "    served_model_id: MODEL_PROVIDER/Model-32B\n"
        "    max_model_len: 16384\n"
        "    deployable: true\n"
    )
    return str(path)


def _settings(registry_file: str, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "auth_enabled": False,
        "safety_enabled": False,
        "events_backend": "stdout",
        "registry_backend": "file",
        "registry_file": registry_file,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def _client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://router") as ac:
            yield ac


@pytest.fixture
async def client(registry_file: str) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(_settings(registry_file)):
        yield c


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).json()["status"] == "ok"
    assert (await client.get("/readyz")).status_code == 200


async def test_models_list(client: httpx.AsyncClient) -> None:
    resp = await client.get("/v1/models")
    ids = {m["id"] for m in resp.json()["data"]}
    assert {"model-8b", "model-32b"} <= ids


async def test_metrics_exposed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"router_requests_total" in resp.content


@respx.mock
async def test_chat_completion_non_stream(client: httpx.AsyncClient) -> None:
    respx.post(f"{UPSTREAM}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "cmpl-1",
                "object": "chat.completion",
                "model": "MODEL_PROVIDER/Model-32B",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hi!"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )
    )
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "model-32b", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "Hi!"
    assert "X-Request-ID" in resp.headers


@respx.mock
async def test_chat_completion_stream_strips_cot(client: httpx.AsyncClient) -> None:
    stream_body = (
        b'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"Answer"}}]}\n\n'
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(f"{UPSTREAM}/v1/chat/completions").mock(
        return_value=httpx.Response(200, content=stream_body)
    )
    async with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "model-8b",
            "mode": "fast",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        },
    ) as resp:
        body = b"".join([chunk async for chunk in resp.aiter_bytes()])
    assert b"hidden" not in body
    assert b"Answer" in body


async def test_context_too_long_returns_structured_error(client: httpx.AsyncClient) -> None:
    huge = "x" * (33000 * 4)  # ~33k tokens, over the 32768 default input cap
    resp = await client.post(
        "/v1/chat/completions",
        json={"model": "model-8b", "messages": [{"role": "user", "content": huge}]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "context_too_long"


async def test_auth_required_when_enabled(registry_file: str) -> None:
    settings = _settings(registry_file, auth_enabled=True, api_keys_file="")
    async for c in _client(settings):
        resp = await c.post(
            "/v1/chat/completions",
            json={"model": "model-8b", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "authentication_failed"
