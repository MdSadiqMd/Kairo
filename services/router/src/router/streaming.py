"""SSE streaming proxy with chain-of-thought stripping.

Hard policy: never stream raw chain-of-thought. Model emits reasoning as a
separate reasoning_content field on the streamed delta; this proxy drops
that field and forwards only final-answer tokens. A concise reasoning summary,
if enabled, is produced after completion — not streamed raw.

The proxy also tallies output tokens and the finish reason so the caller can
emit an accurate InferenceEvent without a second pass.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass
class StreamTally:
    output_tokens: int = 0
    finish_reason: str | None = None
    saw_first_token: bool = False
    _summary_parts: list[str] = field(default_factory=list)
    # Final-answer tokens (CoT already stripped) accumulated for the event's
    # output_raw when raw capture + consent allow it.
    content_parts: list[str] = field(default_factory=list)

    @property
    def output_text(self) -> str:
        return "".join(self.content_parts)


def _sanitize_delta(obj: dict) -> dict:
    """Remove reasoning fields from a streamed chunk in place-safe fashion."""
    for choice in obj.get("choices", []):
        delta = choice.get("delta")
        if isinstance(delta, dict):
            delta.pop("reasoning_content", None)
            delta.pop("reasoning", None)
    return obj


async def sanitize_stream(
    upstream: AsyncIterator[bytes], tally: StreamTally
) -> AsyncIterator[bytes]:
    """Re-frame the upstream SSE stream, stripping CoT and tallying usage."""
    buffer = b""
    async for chunk in upstream:
        buffer += chunk
        while b"\n\n" in buffer:
            raw_event, buffer = buffer.split(b"\n\n", 1)
            out = _process_event(raw_event, tally)
            if out is not None:
                yield out
    if buffer.strip():
        out = _process_event(buffer, tally)
        if out is not None:
            yield out


def _process_event(raw_event: bytes, tally: StreamTally) -> bytes | None:
    line = raw_event.strip()
    if not line.startswith(b"data:"):
        return None
    payload = line[len(b"data:") :].strip()
    if payload == b"[DONE]":
        return b"data: [DONE]\n\n"
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None

    for choice in obj.get("choices", []):
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            tally.saw_first_token = True
            tally.content_parts.append(content)
            # Rough per-chunk token count; exact usage arrives in the final
            # chunk when the server includes it.
            tally.output_tokens += max(1, len(content) // 4)
        if choice.get("finish_reason"):
            tally.finish_reason = choice["finish_reason"]

    usage = obj.get("usage")
    if isinstance(usage, dict) and usage.get("completion_tokens"):
        tally.output_tokens = usage["completion_tokens"]

    obj = _sanitize_delta(obj)
    return b"data: " + json.dumps(obj, separators=(",", ":")).encode() + b"\n\n"
