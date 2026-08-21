"""Per-tenant quota and token-budget enforcement.

A lightweight token-bucket rate limiter plus a context-length guard. This runs
in-process for the MVP; at scale the bucket state moves to MemoryDB/ElastiCache
so it is shared across router replicas. The interface stays the same either way.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from kairo_common import context_too_long, quota_exceeded


@dataclass
class _Bucket:
    tokens: float
    updated: float


class QuotaManager:
    """Token-bucket limiter keyed by tenant.

    rate is requests/second refilled; burst is the bucket size. Values
    are illustrative defaults — production values come from the tenant record in
    the registry.
    """

    def __init__(self, *, rate: float = 20.0, burst: float = 40.0) -> None:
        self._rate = rate
        self._burst = burst
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check_rate(self, tenant_id: str, *, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self._lock:
            b = self._buckets.get(tenant_id) or _Bucket(self._burst, now)
            b.tokens = min(self._burst, b.tokens + (now - b.updated) * self._rate)
            b.updated = now
            if b.tokens < 1.0:
                self._buckets[tenant_id] = b
                raise quota_exceeded("tenant request rate exceeded", tenant_id=tenant_id)
            b.tokens -= 1.0
            self._buckets[tenant_id] = b

    @staticmethod
    def check_context(
        input_tokens: int, requested_output: int, *, max_input: int, max_model_len: int
    ) -> None:
        if input_tokens > max_input:
            raise context_too_long(
                f"input {input_tokens} tokens exceeds limit {max_input}",
                input_tokens=input_tokens,
                limit=max_input,
                param="messages",
            )
        if input_tokens + requested_output > max_model_len:
            raise context_too_long(
                f"input+output {input_tokens + requested_output} exceeds model "
                f"context {max_model_len}",
                limit=max_model_len,
                param="max_tokens",
            )
