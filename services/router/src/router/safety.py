"""Safety classifier client.

The router calls the safety service before choosing a route (see the
sequence diagram): allow / review / block plus a task-type hint. Two hard rules
encoded here:

- Fail closed. If the safety service is unreachable and fail_open is
  False (the production default), the request is blocked, not silently allowed.
- The safety verdict is authoritative for block; review degrades to a
  safer route rather than a hard failure where policy permits.
"""

from __future__ import annotations

import httpx
from kairo_common import get_logger, safety_blocked

from router.schemas import ChatCompletionRequest, SafetyLevel

log = get_logger(__name__)


class SafetyVerdict:
    def __init__(
        self, decision: SafetyLevel, *, task_type: str = "general", reason: str = ""
    ) -> None:
        self.decision = decision
        self.task_type = task_type
        self.reason = reason


class SafetyClient:
    def __init__(
        self,
        *,
        enabled: bool,
        url: str,
        client: httpx.AsyncClient,
        timeout_s: float,
        fail_open: bool,
    ) -> None:
        self._enabled = enabled
        self._url = url.rstrip("/")
        self._client = client
        self._timeout = timeout_s
        self._fail_open = fail_open

    async def classify(
        self, req: ChatCompletionRequest, *, tenant_id: str, request_id: str
    ) -> SafetyVerdict:
        if not self._enabled:
            return SafetyVerdict("allow")
        payload = {
            "tenant_id": tenant_id,
            "request_id": request_id,
            "messages": [m.model_dump(exclude_none=True) for m in req.messages],
            "has_tools": bool(req.tools),
        }
        try:
            resp = await self._client.post(
                f"{self._url}/v1/classify/input",
                json=payload,
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except Exception as exc:
            if self._fail_open:
                log.warning("safety service unavailable; failing open", exc_info=True)
                return SafetyVerdict("allow", reason="fail_open")
            log.error("safety service unavailable; failing closed", exc_info=True)
            raise safety_blocked("safety service unavailable") from exc

        data = resp.json()
        decision: SafetyLevel = data.get("decision", "allow")
        return SafetyVerdict(
            decision,
            task_type=data.get("task_type", "general"),
            reason=data.get("reason", ""),
        )
