from __future__ import annotations

from kairo_ml.rag.chunker import chunk_markdown

_DOC = """# Platform Guide

Intro paragraph about the platform overview and its goals.

## Routing

### Cache-Aware Routing

Route cache-friendly using consistent hashing on a stable prefix key so that
identical prefixes land on the same replica and the prefix cache actually hits.

## Retrieval

Hybrid retrieval combines BM25 and vector search with reciprocal rank fusion.
"""


def test_chunker_preserves_heading_paths() -> None:
    chunks = chunk_markdown(_DOC, "guide", "Platform Guide", target_size=200)
    paths = {chunk.heading_path for chunk in chunks}

    assert ("Platform Guide",) in paths
    assert ("Platform Guide", "Routing", "Cache-Aware Routing") in paths
    assert ("Platform Guide", "Retrieval") in paths


def test_chunker_heading_stack_pops_siblings() -> None:
    chunks = chunk_markdown(_DOC, "guide", "Platform Guide", target_size=200)
    retrieval = next(c for c in chunks if c.heading_path[-1] == "Retrieval")
    # Retrieval is a sibling of Routing at level 2; the deeper Cache-Aware Routing
    # heading must not leak into its path.
    assert retrieval.heading_path == ("Platform Guide", "Retrieval")


def test_chunker_respects_target_size_with_overlap() -> None:
    body = "# H\n\n" + " ".join(f"w{i}" for i in range(100))
    chunks = chunk_markdown(body, "d", "D", target_size=30, overlap=10)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.text.split()) <= 30
    # Overlap: consecutive windows share tokens (step = target - overlap = 20).
    first_tokens = chunks[0].text.split()
    second_tokens = chunks[1].text.split()
    assert first_tokens[20:] == second_tokens[: len(first_tokens) - 20]


def test_chunker_metadata_and_ids() -> None:
    chunks = chunk_markdown(
        _DOC, "guide", "Platform Guide", target_size=200, metadata={"tenant": "acme"}
    )
    assert all(c.metadata["tenant"] == "acme" for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert all(c.chunk_id.startswith("guide::") for c in chunks)


def test_indexable_text_prepends_context() -> None:
    chunks = chunk_markdown("# H\n\nbody text", "d", "D", target_size=200)
    chunk = chunks[0]
    assert chunk.indexable_text() == "body text"
    from dataclasses import replace

    with_context = replace(chunk, context="Document: D")
    assert with_context.indexable_text() == "Document: D\n\nbody text"
