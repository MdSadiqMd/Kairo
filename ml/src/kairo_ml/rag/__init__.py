"""Hybrid RAG subsystem

OpenSearch-style hybrid retrieval - lexical (BM25) plus dense (embeddings) fused
with Reciprocal Rank Fusion and reranked, never vector-only. `HybridRetriever`
is the main entrypoint
"""

from __future__ import annotations

from kairo_ml.rag.bm25 import BM25Index, tokenize
from kairo_ml.rag.chunker import Chunk, chunk_markdown
from kairo_ml.rag.contextualize import (
    Contextualizer,
    LLMContextualizer,
    TemplateContextualizer,
)
from kairo_ml.rag.embeddings import (
    BedrockEmbedder,
    Embedder,
    HashEmbedder,
    cosine_similarity,
)
from kairo_ml.rag.evals import (
    citation_accuracy,
    faithfulness,
    mean_reciprocal_rank,
    mean_reciprocal_rank_over_queries,
    recall_at_k,
)
from kairo_ml.rag.fusion import reciprocal_rank_fusion
from kairo_ml.rag.prompt_assembly import (
    AssembledPrompt,
    Citation,
    assemble_grounded_prompt,
)
from kairo_ml.rag.rerank import (
    CrossEncoderReranker,
    HeuristicReranker,
    Reranker,
)
from kairo_ml.rag.retriever import Document, HybridRetriever, RetrievedChunk
from kairo_ml.rag.vector_index import (
    InMemoryVectorIndex,
    OpenSearchVectorIndex,
    VectorIndex,
)

__all__ = [
    "AssembledPrompt",
    "BM25Index",
    "BedrockEmbedder",
    "Chunk",
    "Citation",
    "Contextualizer",
    "CrossEncoderReranker",
    "Document",
    "Embedder",
    "HashEmbedder",
    "HeuristicReranker",
    "HybridRetriever",
    "InMemoryVectorIndex",
    "LLMContextualizer",
    "OpenSearchVectorIndex",
    "Reranker",
    "RetrievedChunk",
    "TemplateContextualizer",
    "VectorIndex",
    "assemble_grounded_prompt",
    "chunk_markdown",
    "citation_accuracy",
    "cosine_similarity",
    "faithfulness",
    "mean_reciprocal_rank",
    "mean_reciprocal_rank_over_queries",
    "recall_at_k",
    "reciprocal_rank_fusion",
    "tokenize",
]
