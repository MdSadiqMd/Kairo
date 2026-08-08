"""Hybrid retriever orchestrator

HybridRetriever is the main entrypoint for the RAG subsystem. It wires the
components into one flow:

Indexing:   document -> chunk (heading-aware) -> contextualize -> {BM25, vector}
Querying:   query -> {BM25 results, vector results} -> RRF -> rerank -> top-K

The result is a list of RetrievedChunk carrying the chunk plus its source
metadata, ready for grounded prompt assembly. This is deliberately hybrid
(lexical + dense), never vector-only
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from kairo_common import get_logger

from kairo_ml.rag.bm25 import BM25Index
from kairo_ml.rag.chunker import Chunk, chunk_markdown
from kairo_ml.rag.contextualize import Contextualizer, TemplateContextualizer
from kairo_ml.rag.embeddings import Embedder
from kairo_ml.rag.fusion import reciprocal_rank_fusion
from kairo_ml.rag.rerank import HeuristicReranker, Reranker
from kairo_ml.rag.vector_index import InMemoryVectorIndex, VectorIndex

logger = get_logger(__name__)


@dataclass(frozen=True)
class Document:
    """An input document to be chunked and indexed"""

    doc_id: str
    title: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned from a query, with its final rerank score"""

    chunk: Chunk
    score: float


class HybridRetriever:
    """Orchestrates chunking, contextualization, hybrid retrieval, and reranking"""

    def __init__(
        self,
        embedder: Embedder,
        *,
        vector_index: VectorIndex | None = None,
        bm25_index: BM25Index | None = None,
        contextualizer: Contextualizer | None = None,
        reranker: Reranker | None = None,
        target_chunk_size: int = 120,
        chunk_overlap: int = 24,
        candidate_k: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.embedder = embedder
        self.vector_index = vector_index if vector_index is not None else InMemoryVectorIndex()
        self.bm25_index = bm25_index if bm25_index is not None else BM25Index()
        self.contextualizer = (
            contextualizer if contextualizer is not None else TemplateContextualizer()
        )
        self.reranker = reranker if reranker is not None else HeuristicReranker()
        self.target_chunk_size = target_chunk_size
        self.chunk_overlap = chunk_overlap
        self.candidate_k = candidate_k
        self.rrf_k = rrf_k
        self._chunks: dict[str, Chunk] = {}

    def index_document(self, document: Document) -> list[Chunk]:
        chunks = chunk_markdown(
            document.text,
            document.doc_id,
            document.title,
            target_size=self.target_chunk_size,
            overlap=self.chunk_overlap,
            metadata=document.metadata,
        )
        contextualized: list[Chunk] = []
        for chunk in chunks:
            context = self.contextualizer.contextualize(chunk)
            enriched = Chunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                heading_path=chunk.heading_path,
                context=context,
                metadata=chunk.metadata,
            )
            contextualized.append(enriched)

        if not contextualized:
            return []

        indexable = [c.indexable_text() for c in contextualized]
        vectors = self.embedder.embed(indexable)
        self.vector_index.add(
            (c.chunk_id, vector) for c, vector in zip(contextualized, vectors, strict=True)
        )
        for chunk, text in zip(contextualized, indexable, strict=True):
            self.bm25_index.add(chunk.chunk_id, text)
            self._chunks[chunk.chunk_id] = chunk
        return contextualized

    def index_documents(self, documents: Sequence[Document]) -> int:
        total = 0
        for document in documents:
            total += len(self.index_document(document))
        return total

    def query(self, query: str, *, top_k: int = 5) -> list[RetrievedChunk]:
        if not self._chunks:
            return []
        bm25_hits = self.bm25_index.search(query, k=self.candidate_k)
        query_vector = self.embedder.embed([query])[0]
        vector_hits = self.vector_index.search(query_vector, k=self.candidate_k)

        bm25_ids = [doc_id for doc_id, _ in bm25_hits]
        vector_ids = [doc_id for doc_id, _ in vector_hits]
        fused = reciprocal_rank_fusion([bm25_ids, vector_ids], k=self.rrf_k)

        # Take the fused candidates that we actually have chunks for, then rerank.
        candidate_ids = [doc_id for doc_id, _ in fused if doc_id in self._chunks]
        candidates = [self._chunks[doc_id] for doc_id in candidate_ids[: self.candidate_k]]
        if not candidates:
            return []
        reranked = self.reranker.rerank(query, candidates, top_k=top_k)
        return [RetrievedChunk(chunk=chunk, score=score) for chunk, score in reranked]
