"""Structured inference event

Every inference request emits exactly one of these to the event stream. By
default it carries hashes and metadata only — raw prompt/output storage is
disabled unless consent and tenant policy allow it. This model is the
contract shared by the router (producer) and the log_ingestor (consumer); the
Go ingestor validates against the same field set
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

Route = Literal["fast", "normal", "reasoning", "agent", "batch"]
SafetyDecision = Literal["allow", "review", "block"]
FinishReason = Literal["stop", "length", "tool_calls", "content_filter", "error"]


class InferenceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    request_id: str
    timestamp: str  # ISO-8601, stamped by the producer
    tenant_id: str
    route: Route
    model: str
    model_version: str
    prompt_hash: str  # sha256 of the normalized prompt; never the prompt itself
    input_tokens: int
    output_tokens: int
    latency_ms: int
    ttft_ms: int | None = None
    tpot_ms: float | None = None
    finish_reason: FinishReason | None = None
    safety_decision: SafetyDecision = "allow"
    tool_calls_count: int = 0
    verifier_score: float | None = None
    user_feedback: str | None = None
    training_consent: bool = False
    # Policy version of the serving model (from the registry); the online RL
    # staleness guard compares this against the trainer's current policy step.
    policy_version: int = 0
    # Optional raw payloads — populated ONLY when training_consent and tenant
    # policy both allow it. Redaction happens downstream in the data plane.
    prompt_raw: str | None = Field(default=None, repr=False)
    output_raw: str | None = Field(default=None, repr=False)

    def to_stream_record(self) -> bytes:
        """Serialize for Kinesis/SQS. Newline-delimited JSON, UTF-8."""
        return (self.model_dump_json(exclude_none=True) + "\n").encode("utf-8")
