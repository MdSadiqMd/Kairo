from __future__ import annotations

from kairo_ml.rag.contextualize import TemplateContextualizer
from kairo_ml.rag.embeddings import HashEmbedder
from kairo_ml.rag.rerank import HeuristicReranker
from kairo_ml.rag.retriever import Document, HybridRetriever

_CORPUS = [
    Document(
        doc_id="routing",
        title="Router Design",
        text=(
            "# Router Design\n\n"
            "## Cache-Aware Routing\n\n"
            "The router hashes a stable prefix key and uses consistent hashing to "
            "route identical prefixes to the same replica so the prefix cache hits. "
            "Session affinity keeps a growing multi-turn prefix on one replica.\n\n"
            "## Load Balancing\n\n"
            "Fall back to least-loaded when the preferred replica queue is saturated."
        ),
    ),
    Document(
        doc_id="safety",
        title="Safety Classifier",
        text=(
            "# Safety Classifier\n\n"
            "The safety classifier screens prompts for policy violations before the "
            "model runs and blocks disallowed content."
        ),
    ),
    Document(
        doc_id="cooking",
        title="Sourdough Guide",
        text=(
            "# Sourdough Guide\n\n"
            "Feed the starter with flour and water; bulk ferment the dough overnight."
        ),
    ),
]


def _build() -> HybridRetriever:
    retriever = HybridRetriever(
        HashEmbedder(dim=512),
        contextualizer=TemplateContextualizer(),
        reranker=HeuristicReranker(),
        target_chunk_size=60,
        chunk_overlap=12,
    )
    retriever.index_documents(_CORPUS)
    return retriever


def test_hybrid_retriever_finds_relevant_chunk() -> None:
    retriever = _build()
    results = retriever.query("how does consistent hashing keep the prefix cache warm", top_k=3)

    assert results
    top = results[0].chunk
    assert top.doc_id == "routing"
    assert top.heading_path == ("Router Design", "Cache-Aware Routing")
    assert "consistent hashing" in top.text


def test_hybrid_retriever_excludes_irrelevant_topic() -> None:
    retriever = _build()
    results = retriever.query("consistent hashing prefix cache replica routing", top_k=2)
    doc_ids = {r.chunk.doc_id for r in results}
    assert "cooking" not in doc_ids


def test_query_before_index_returns_empty() -> None:
    retriever = HybridRetriever(HashEmbedder(dim=64))
    assert retriever.query("anything") == []


def test_lexical_only_term_is_retrievable() -> None:
    # A rare exact identifier is where BM25 carries the hybrid — dense embeddings
    # alone often miss it.
    retriever = _build()
    results = retriever.query("least-loaded saturated queue fall back", top_k=3)
    assert any("least-loaded" in r.chunk.text for r in results)


def test_scores_are_descending() -> None:
    retriever = _build()
    results = retriever.query("cache-aware routing consistent hashing", top_k=5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
