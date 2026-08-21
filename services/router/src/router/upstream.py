"""Upstream model-server client (vLLM / SGLang, OpenAI-compatible).

Forwards normalized requests to the internal model server and returns either a
full response or an async stream of SSE lines. Only the router is exposed
publicly; the model servers stay inside the cluster, and the dangerous
vLLM dev endpoints are never called from here.

X-Request-ID is propagated to the upstream so a single id spans client →
router → GPU pod.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from kairo_common import get_logger, model_unavailable, upstream_timeout
from kairo_common.ids import REQUEST_ID_HEADER

log = get_logger(__name__)


class UpstreamClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def chat_completion(
        self, endpoint: str, body: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        url = f"{endpoint.rstrip('/')}/v1/chat/completions"
        try:
            resp = await self._client.post(
                url, json={**body, "stream": False}, headers={REQUEST_ID_HEADER: request_id}
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException as exc:
            raise upstream_timeout(endpoint=endpoint) from exc
        except httpx.HTTPStatusError as exc:
            raise model_unavailable(
                f"upstream returned {exc.response.status_code}", endpoint=endpoint
            ) from exc
        except httpx.HTTPError as exc:
            raise model_unavailable("upstream connection error", endpoint=endpoint) from exc


async def stream_chat_completion(
    self, endpoint: str, body: dict[str, Any], *, request_id: str
) -> AsyncIterator[bytes]:
    """Yield raw SSE lines (data: {...}\n\n) from the upstream.

    The caller (streaming.py) is responsible for policy — e.g. never
    forwarding raw chain-of-thought.
    """
    url = f"{endpoint.rstrip('/')}/v1/chat/completions"
    try:
        async with self._client.stream(
            "POST",
            url,
            json={**body, "stream": True},
            headers={REQUEST_ID_HEADER: request_id},
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk
    except httpx.TimeoutException as exc:
        raise upstream_timeout(endpoint=endpoint) from exc
    except httpx.HTTPError as exc:
        raise model_unavailable("upstream stream error", endpoint=endpoint) from exc
