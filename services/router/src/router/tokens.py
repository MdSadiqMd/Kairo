"""Cheap, dependency-free token estimation.

The router needs a fast pre-flight token estimate to enforce context limits and
quotas before calling the model server — the exact count comes back from the
server's usage field. We deliberately avoid bundling a tokenizer in the hot
path; a chars/4 heuristic with a per-message overhead is close enough to gate
on, and always rounds slightly high so we never under-count against a limit.
"""

from __future__ import annotations

from collections.abc import Iterable

from router.schemas import ChatMessage

_CHARS_PER_TOKEN = 4
_PER_MESSAGE_OVERHEAD = 4  # role/format framing tokens per message


def estimate_message_tokens(messages: Iterable[ChatMessage]) -> int:
    total = 0
    for m in messages:
        total += _PER_MESSAGE_OVERHEAD
        content = m.content
        if isinstance(content, str):
            total += _len_to_tokens(len(content))
        elif isinstance(content, list):
            for part in content:
                text = part.get("text", "") if isinstance(part, dict) else ""
                total += _len_to_tokens(len(text))
    return total


def _len_to_tokens(char_len: int) -> int:
    # Round up so estimates never undercount against a hard limit.
    return (char_len + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN
