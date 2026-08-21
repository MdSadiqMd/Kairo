"""Request/response schemas for the safety classifier service.

The input-classification contract here is exactly what the router's
SafetyClient calls (services/router/src/router/safety.py): POST
/v1/classify/input with messages, receive {decision, task_type, reason}.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class InputRequest(BaseModel):
    tenant_id: str
    request_id: str
    messages: list[dict[str, Any]]
    has_tools: bool = False


class InputResponse(BaseModel):
    decision: Literal["allow", "review", "block"]
    task_type: str
    reason: str = ""


class OutputRequest(BaseModel):
    tenant_id: str
    request_id: str
    text: str


class OutputResponse(BaseModel):
    decision: Literal["allow", "review", "block"]
    reason: str = ""
    redactions: int = 0


class ActionRequest(BaseModel):
    tenant_id: str
    request_id: str
    action: str
    target: str | None = None


class ActionResponse(BaseModel):
    decision: Literal["allow", "ask_user", "block"]
    risk_level: Literal["low", "medium", "high", "critical"]
    reason: str
    safer_alternative: str | None = None
