"""Chunk contextualization

Implements Anthropic's Contextual Retrieval idea: before a chunk is embedded and
indexed, prepend a short natural-language description situating it within its
document. This disambiguates chunks whose meaning depends on surrounding context
(pronouns, relative figures, section-local jargon), improving both lexical and
dense recall

Two implementations of the `Contextualizer` protocol:

- `TemplateContextualizer` — deterministic; builds the context from the document
  title, the heading path, and a one-line summary heuristic. No network, no model.
- `LLMContextualizer` — calls the platform router (an OpenAI-compatible chat
  endpoint) over httpx to generate the context. httpx is imported lazily so
  the deterministic path stays dependency-light and offline-safe
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from kairo_common import get_logger

from kairo_ml.rag.chunker import Chunk

logger = get_logger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


class Contextualizer(Protocol):
    """Produces a short context string to prepend to a chunk before embedding"""

    def contextualize(self, chunk: Chunk) -> str: ...


def _one_line_summary(text: str, max_chars: int = 160) -> str:
    """First sentence of the chunk, truncated — a cheap stand-in for a summary"""
    stripped = text.strip()
    if not stripped:
        return ""
    first = _SENTENCE_END.split(stripped, maxsplit=1)[0]
    first = " ".join(first.split())
    if len(first) > max_chars:
        return first[: max_chars - 1].rstrip() + "…"
    return first


class TemplateContextualizer:
    """Deterministic context: document title + heading path + summary heuristic"""

    def contextualize(self, chunk: Chunk) -> str:
        parts = [f"Document: {chunk.doc_title}"]
        if chunk.heading_path:
            parts.append("Section: " + " > ".join(chunk.heading_path))
        summary = _one_line_summary(chunk.text)
        if summary:
            parts.append(f"Summary: {summary}")
        return " | ".join(parts)


class LLMContextualizer:
    """Router-backed contextualizer (lazy httpx import)

    Calls an OpenAI-compatible chat completion on the platform router to write a
    one-sentence situating context for the chunk. On any transport error it falls
    back to the deterministic template so indexing never hard-fails on a flaky
    router — a degraded context is better than an unindexed chunk
    """

    def __init__(
        self,
        router_url: str,
        *,
        model: str = "model-30b-a3b",
        timeout: float = 15.0,
        api_key: str | None = None,
    ) -> None:
        self.router_url = router_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._fallback = TemplateContextualizer()

    def _build_prompt(self, chunk: Chunk) -> str:
        location = " > ".join(chunk.heading_path) if chunk.heading_path else "(top level)"
        return (
            f"Document title: {chunk.doc_title}\n"
            f"Section path: {location}\n"
            f"Chunk:\n{chunk.text}\n\n"
            "Write a single short sentence that situates this chunk within the "
            "document so it can be understood on its own. Output only the sentence"
        )

    def contextualize(self, chunk: Chunk) -> str:
        import httpx  # lazy: keep the network client off the deterministic path

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": self._build_prompt(chunk)}],
            "max_tokens": 128,
            "temperature": 0.0,
        }
        try:
            response = httpx.post(
                f"{self.router_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            context = " ".join(str(content).split())
            if context:
                return context
        except Exception as exc:
            logger.warning("LLM contextualizer failed, using template fallback: %s", exc)
        return self._fallback.contextualize(chunk)
