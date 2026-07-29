"""Structured JSON logging with request-scoped context

Context is propagated via ``contextvars`` so handlers deep in the call stack do
not need the fields threaded through every signature
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

# Default is None (immutable) rather than a shared dict - every write does a
# fresh .set(), so context never mutates in place
_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "log_context", default=None
)


def _current() -> dict[str, Any]:
    return _context.get() or {}


_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_current())
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Uvicorn access logs are noisy and duplicate our structured request logs
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def request_context(**fields: Any) -> Iterator[None]:
    """Bind fields onto every log line emitted within the block."""
    current = _current()
    token = _context.set({**current, **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def bind(**fields: Any) -> None:
    """Merge fields into the current context without a new scope."""
    current = _current()
    _context.set({**current, **{k: v for k, v in fields.items() if v is not None}})
