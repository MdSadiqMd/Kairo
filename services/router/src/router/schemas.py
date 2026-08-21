"""OpenAI-compatible request/response schemas and the internal RequestContext.

The public surface mirrors OpenAI's Chat Completions API so existing SDKs work
unchanged. The internal RequestContext is the router's
own normalized view carried through routing, budgeting, and telemetry.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Route = Literal["fast", "normal", "reasoning", "agent", "batch"]
ThinkingBudget = Literal["none", "low", "medium", "high", "max"]
SafetyLevel = Literal["allow", "review", "block"]
PublicMode = Literal["fast", "normal", "deep", "max"]


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str | list[dict[str, Any]] | None = None
    name: str | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    """Subset of the OpenAI chat request plus our mode extension."""

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    user: str | None = None
    # Extensions (namespaced so they never collide with upstream params).
    mode: PublicMode | None = Field(default=None, description="fast|normal|deep|max")
    metadata: dict[str, Any] | None = None

    def resolved_max_output_tokens(self, default: int) -> int:
        return self.max_completion_tokens or self.max_tokens or default


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: ChatMessage
    finish_reason: str | None = None


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionChoice]
    usage: Usage = Field(default_factory=Usage)


class ModelCard(BaseModel):
    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "Kairo"


class ModelList(BaseModel):
    object: Literal["list"] = "list"
    data: list[ModelCard]


class RequestContext(BaseModel):
    """The router's normalized internal view of a request."""

    request_id: str
    tenant_id: str
    user_id: str | None = None
    model_requested: str | None = None
    route: Route
    thinking_budget: ThinkingBudget
    safety_level: SafetyLevel = "allow"
    max_input_tokens: int
    max_output_tokens: int
    deadline_ms: int
    trace_id: str
    # Resolved during routing; populated before the upstream call.
    target_model: str = ""
    target_model_version: str = ""
    candidates: int = 1
    use_verifier: bool = False
    tools_allowed: bool = False
    cache_prefix_key: str = ""
