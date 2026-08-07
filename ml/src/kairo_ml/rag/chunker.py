"""Domain-aware chunking

Markdown-aware chunking that preserves the heading hierarchy. Each chunk carries
the full heading path of the section it came from, so downstream contextualization
and prompt assembly can cite where in a document a
passage lives, not just which document. Sections larger than the target size are
split into overlapping windows so no chunk exceeds the budget while adjacent chunks
still share context across the split boundary

Pure Python; no external dependencies
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit of a document plus the metadata needed to cite it"""

    chunk_id: str
    text: str
    doc_id: str
    doc_title: str
    heading_path: tuple[str, ...]
    context: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    def indexable_text(self) -> str:
        """Text fed to the lexical/vector indexes: prepend the context string

        Contextual Retrieval embeds `context + body` rather than the raw
        body so a chunk that says "it declined 3%" is disambiguated by a prefix
        like "This chunk is from ACME's Q2 report; revenue section." When no
        contextualizer has run, `context` is empty and this is just the body.
        """
        if self.context:
            return f"{self.context}\n\n{self.text}"
        return self.text


def _split_windows(tokens: Sequence[str], target_size: int, overlap: int) -> Iterator[list[str]]:
    """Yield overlapping token windows. Step = target_size - overlap"""
    if len(tokens) <= target_size:
        yield list(tokens)
        return
    step = max(1, target_size - overlap)
    start = 0
    while start < len(tokens):
        yield list(tokens[start : start + target_size])
        if start + target_size >= len(tokens):
            break
        start += step


@dataclass
class _Section:
    heading_path: tuple[str, ...]
    lines: list[str]

    def body(self) -> str:
        return "\n".join(self.lines).strip()


def _iter_sections(text: str) -> Iterator[_Section]:
    """Walk the document, emitting one section per heading run

    A running stack keyed by heading level reconstructs the path: a level-N
    heading pops every stack entry at level >= N before pushing itself, so
    `## A` then `### B` then `## C` yields paths `(A,)`, `(A, B)`, `(C,)`
    """
    stack: list[tuple[int, str]] = []
    current: list[str] = []
    path: tuple[str, ...] = ()

    def current_path() -> tuple[str, ...]:
        return tuple(title for _, title in stack)

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match is None:
            current.append(line)
            continue
        if current:
            yield _Section(path, current)
            current = []
        level = len(match.group(1))
        title = match.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        path = current_path()
    if current:
        yield _Section(path, current)


def chunk_markdown(
    text: str,
    doc_id: str,
    doc_title: str,
    *,
    target_size: int = 120,
    overlap: int = 24,
    metadata: dict[str, str] | None = None,
) -> list[Chunk]:
    """Chunk a markdown document, preserving heading paths

    Args:
        target_size: target chunk length in whitespace tokens
        overlap: token overlap between adjacent windows of an oversized section
    """
    if overlap >= target_size:
        raise ValueError("overlap must be smaller than target_size")
    base_metadata = dict(metadata or {})
    chunks: list[Chunk] = []
    for section in _iter_sections(text):
        body = section.body()
        if not body:
            continue
        tokens = body.split()
        for window in _split_windows(tokens, target_size, overlap):
            chunk_text = " ".join(window)
            chunk = Chunk(
                chunk_id=f"{doc_id}::{len(chunks)}",
                text=chunk_text,
                doc_id=doc_id,
                doc_title=doc_title,
                heading_path=section.heading_path,
                metadata=dict(base_metadata),
            )
            chunks.append(chunk)
    return chunks
