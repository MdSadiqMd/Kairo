"""
Every failure surfaced to a client maps to a stable, enumerated code so that
clients can branch on ``error.code`` rather than parsing prose, and so that
dashboards can aggregate failures by code. Retrofitting this later costs ~10x,
so the taxonomy is defined once, here, and reused across every service
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    QUOTA_EXCEEDED = "quota_exceeded"
    CONTEXT_TOO_LONG = "context_too_long"
    SAFETY_BLOCKED = "safety_blocked"
    MODEL_UNAVAILABLE = "model_unavailable"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_ERROR = "upstream_error"
    INVALID_REQUEST = "invalid_request"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    INTERNAL_ERROR = "internal_error"


_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.QUOTA_EXCEEDED: 429,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.CONTEXT_TOO_LONG: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.SAFETY_BLOCKED: 403,
    ErrorCode.AUTHENTICATION_FAILED: 401,
    ErrorCode.MODEL_UNAVAILABLE: 503,
    ErrorCode.UPSTREAM_TIMEOUT: 504,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.INTERNAL_ERROR: 500,
}


class PlatformError(Exception):
    """An error with a stable code, HTTP status, and OpenAI-shaped body.

    ``retriable`` tells clients (and the router's own fallback logic) whether a
    retry could plausibly succeed. ``details`` carries structured, non-sensitive
    context for logging — never raw prompts or model output.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int | None = None,
        retriable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status if http_status is not None else _HTTP_STATUS[code]
        self.retriable = retriable
        self.details = details or {}

    def to_openai_error(self) -> dict[str, Any]:
        """Render as an OpenAI-compatible error envelope."""
        return {
            "error": {
                "message": self.message,
                "type": self.code.value,
                "code": self.code.value,
                "param": self.details.get("param"),
            }
        }


def quota_exceeded(
    message: str = "Tenant token/request quota exceeded", **details: Any
) -> PlatformError:
    return PlatformError(ErrorCode.QUOTA_EXCEEDED, message, retriable=True, details=details)


def context_too_long(message: str, **details: Any) -> PlatformError:
    return PlatformError(ErrorCode.CONTEXT_TOO_LONG, message, retriable=False, details=details)


def safety_blocked(
    message: str = "Request blocked by safety policy", **details: Any
) -> PlatformError:
    return PlatformError(ErrorCode.SAFETY_BLOCKED, message, retriable=False, details=details)


def model_unavailable(message: str, **details: Any) -> PlatformError:
    return PlatformError(ErrorCode.MODEL_UNAVAILABLE, message, retriable=True, details=details)


def upstream_timeout(
    message: str = "Upstream model server timed out", **details: Any
) -> PlatformError:
    return PlatformError(ErrorCode.UPSTREAM_TIMEOUT, message, retriable=True, details=details)
