from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from eval_api.main import build_app


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(registry_dir="ml/evals/registry")
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://eval") as ac:
            yield ac


async def test_list_and_get_specs(client: httpx.AsyncClient) -> None:
    suites = (await client.get("/v1/evals")).json()["suites"]
    assert "smoke_v1" in suites
    spec = (await client.get("/v1/evals/smoke_v1")).json()
    assert spec["runner"] == "smoke"
    assert (await client.get("/v1/evals/does_not_exist")).status_code == 404


async def test_gate_evaluate_blocks_and_passes(client: httpx.AsyncClient) -> None:
    def run(passes: int, n: int) -> dict:
        return {
            "eval_run_id": "e",
            "suite": "smoke_v1",
            "model": "m",
            "model_version": "v",
            "items": [
                {"item_id": str(i), "passed": i < passes, "latency_ms": 50} for i in range(n)
            ],
        }

    ok = await client.post(
        "/v1/gate/evaluate", json={"suite": "smoke_v1", "candidate": run(10, 10)}
    )
    assert ok.json()["promotable"] is True

    bad = await client.post(
        "/v1/gate/evaluate", json={"suite": "smoke_v1", "candidate": run(2, 10)}
    )
    body = bad.json()
    assert body["promotable"] is False
    assert any(not c["passed"] for c in body["checks"])
