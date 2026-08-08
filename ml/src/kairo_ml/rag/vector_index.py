"""Vector indexes

The VectorIndex protocol abstracts the dense-retrieval backend. Two
implementations:
- InMemoryVectorIndex — brute-force cosine top-k. The default; it is what
  tests use and is adequate for small corpora and local development
- OpenSearchVectorIndex — a k-NN index backed by OpenSearch (the platform's
  production vector store). It lazily imports opensearchpy so this
  module loads offline without the dependency installed
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from kairo_ml.rag.embeddings import cosine_similarity


class VectorIndex(Protocol):
    """A dense index mapping ids to vectors, queryable by nearest neighbor"""

    def add(self, entries: Iterable[tuple[str, Sequence[float]]]) -> None: ...

    def search(self, vector: Sequence[float], k: int) -> list[tuple[str, float]]: ...


class InMemoryVectorIndex:
    """Brute-force cosine similarity index. O(n) per query"""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._vectors: list[list[float]] = []

    def __len__(self) -> int:
        return len(self._ids)

    def add(self, entries: Iterable[tuple[str, Sequence[float]]]) -> None:
        for entry_id, vector in entries:
            self._ids.append(entry_id)
            self._vectors.append([float(x) for x in vector])

    def search(self, vector: Sequence[float], k: int) -> list[tuple[str, float]]:
        scored = [
            (entry_id, cosine_similarity(vector, stored))
            for entry_id, stored in zip(self._ids, self._vectors, strict=True)
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


class OpenSearchVectorIndex:
    """OpenSearch k-NN vector index (lazy opensearchpy import)

    Uses the knn query over a knn_vector field. Construction of the client
    and index bootstrap are deferred so importing this module offline is safe
    """

    def __init__(
        self,
        index_name: str,
        *,
        hosts: Sequence[str] | None = None,
        dim: int = 1024,
        vector_field: str = "embedding",
    ) -> None:
        self.index_name = index_name
        self.hosts = list(hosts) if hosts is not None else ["localhost:9200"]
        self.dim = dim
        self.vector_field = vector_field
        self._client: Any = None

    def _ensure_client(self) -> Any:
        if self._client is None:
            from opensearchpy import OpenSearch  # lazy: optional 'rag' extra

            self._client = OpenSearch(hosts=self.hosts)
            if not self._client.indices.exists(index=self.index_name):
                self._client.indices.create(
                    index=self.index_name,
                    body={
                        "settings": {"index": {"knn": True}},
                        "mappings": {
                            "properties": {
                                self.vector_field: {
                                    "type": "knn_vector",
                                    "dimension": self.dim,
                                }
                            }
                        },
                    },
                )
        return self._client

    def add(self, entries: Iterable[tuple[str, Sequence[float]]]) -> None:
        client = self._ensure_client()
        for entry_id, vector in entries:
            client.index(
                index=self.index_name,
                id=entry_id,
                body={self.vector_field: [float(x) for x in vector]},
            )
        client.indices.refresh(index=self.index_name)

    def search(self, vector: Sequence[float], k: int) -> list[tuple[str, float]]:
        client = self._ensure_client()
        response = client.search(
            index=self.index_name,
            body={
                "size": k,
                "query": {
                    "knn": {
                        self.vector_field: {
                            "vector": [float(x) for x in vector],
                            "k": k,
                        }
                    }
                },
            },
        )
        hits = response["hits"]["hits"]
        return [(hit["_id"], float(hit["_score"])) for hit in hits]
