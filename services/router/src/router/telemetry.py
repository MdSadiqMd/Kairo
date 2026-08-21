"""Prometheus metrics and structured event emission.

Metrics are the serving-layer signals used for SLOs and — critically — for
autoscaling: queue depth, TTFT, TPOT, tokens/s, cache-hit rate. CPU is
explicitly not an autoscaling signal for GPU LLM serving. Events are the data
plane's raw feed: one structured event per request, hashes and metadata
by default, raw payloads only under consent.
"""

from __future__ import annotations

import hashlib
import sys
from typing import Protocol

from kairo_common import InferenceEvent, get_logger
from prometheus_client import Counter, Gauge, Histogram

log = get_logger(__name__)

REQUESTS = Counter(
    "router_requests_total", "Requests by route and outcome", ["route", "model", "outcome"]
)
TTFT = Histogram(
    "router_ttft_seconds",
    "Time to first token",
    ["route", "model"],
    buckets=(0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.3, 2.0, 3.0, 5.0, 8.0),
)
E2E_LATENCY = Histogram(
    "router_request_seconds",
    "End-to-end request latency",
    ["route", "model"],
    buckets=(0.1, 0.3, 0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
OUTPUT_TOKENS = Histogram(
    "router_output_tokens",
    "Output tokens per request",
    ["route", "model"],
    buckets=(16, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384),
)
INFLIGHT = Gauge("router_inflight_requests", "In-flight requests", ["route"])
SAFETY_BLOCKS = Counter("router_safety_blocks_total", "Safety blocks", ["decision"])
CACHE_ROUTED = Counter("router_cache_routed_total", "Cache-affinity routing outcomes", ["outcome"])


def prompt_hash(messages_text: str) -> str:
    return hashlib.sha256(messages_text.encode()).hexdigest()


class EventSink(Protocol):
    def emit(self, event: InferenceEvent) -> None: ...


class StdoutEventSink:
    """Local/dev sink: write NDJSON to stdout. The Go log_ingestor consumes the
    same schema off Kinesis in production."""

    def emit(self, event: InferenceEvent) -> None:
        sys.stdout.buffer.write(event.to_stream_record())
        sys.stdout.buffer.flush()


def build_event_sink(backend: str, stream: str) -> EventSink:
    if backend == "stdout":
        return StdoutEventSink()
    from router.event_sinks_aws import build_aws_sink

    return build_aws_sink(backend, stream)
