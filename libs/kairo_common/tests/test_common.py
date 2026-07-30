from __future__ import annotations

import json
import logging

from kairo_common import (
    ErrorCode,
    InferenceEvent,
    PlatformError,
    context_too_long,
    new_request_id,
    quota_exceeded,
)
from kairo_common.ids import coerce_request_id
from kairo_common.logging import JsonFormatter, request_context


def test_error_maps_to_http_and_openai_envelope() -> None:
    err = quota_exceeded(param="messages")
    assert err.code is ErrorCode.QUOTA_EXCEEDED
    assert err.http_status == 429
    assert err.retriable is True
    body = err.to_openai_error()
    assert body["error"]["code"] == "quota_exceeded"
    assert body["error"]["param"] == "messages"


def test_context_too_long_is_not_retriable() -> None:
    err = context_too_long("prompt is 40000 tokens, limit is 16384")
    assert err.retriable is False
    assert err.http_status == 400


def test_platform_error_custom_status() -> None:
    err = PlatformError(ErrorCode.INTERNAL_ERROR, "boom", http_status=500)
    assert err.http_status == 500


def test_request_id_shape_and_coercion() -> None:
    rid = new_request_id()
    assert rid.startswith("req_")
    assert coerce_request_id("client-supplied-1234") == "client-supplied-1234"
    assert coerce_request_id("short").startswith("req_")
    assert coerce_request_id(None).startswith("req_")


def test_inference_event_serializes_without_raw_by_default() -> None:
    event = InferenceEvent(
        request_id="req_1",
        timestamp="2026-07-11T00:00:00Z",
        tenant_id="acme",
        route="reasoning",
        model="model-32b",
        model_version="2026-07-11-001",
        prompt_hash="abc",
        input_tokens=10,
        output_tokens=20,
        latency_ms=1000,
    )
    record = json.loads(event.to_stream_record())
    assert record["schema_version"] == "1.0"
    assert "prompt_raw" not in record
    assert record["training_consent"] is False


def test_inference_event_rejects_unknown_fields() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InferenceEvent(
            request_id="r",
            timestamp="t",
            tenant_id="a",
            route="fast",
            model="m",
            model_version="v",
            prompt_hash="h",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            bogus_field="x",
        )


def test_json_formatter_includes_bound_context() -> None:
    formatter = JsonFormatter("test-service")
    with request_context(request_id="req_9", tenant_id="acme"):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
        record.route = "fast"
        out = json.loads(formatter.format(record))
    assert out["request_id"] == "req_9"
    assert out["tenant_id"] == "acme"
    assert out["route"] == "fast"
    assert out["service"] == "test-service"
    assert out["message"] == "hello"
