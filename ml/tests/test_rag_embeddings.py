from __future__ import annotations

from kairo_ml.rag.embeddings import HashEmbedder, cosine_similarity
from kairo_ml.rag.vector_index import InMemoryVectorIndex


def test_hash_embedder_is_deterministic() -> None:
    embedder = HashEmbedder(dim=128)
    a = embedder.embed(["kubernetes autoscaling"])[0]
    b = embedder.embed(["kubernetes autoscaling"])[0]
    assert a == b
    assert len(a) == 128


def test_hash_embedder_similar_texts_score_higher() -> None:
    embedder = HashEmbedder(dim=512)
    query, near, far = embedder.embed(
        [
            "pod autoscaling on kubernetes",
            "kubernetes autoscaling for pods",
            "arctic bird migration patterns",
        ]
    )
    assert cosine_similarity(query, near) > cosine_similarity(query, far)


def test_cosine_similarity_zero_norm() -> None:
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_in_memory_vector_index_topk() -> None:
    embedder = HashEmbedder(dim=256)
    index = InMemoryVectorIndex()
    docs = {
        "d1": "hybrid retrieval bm25 and vector search",
        "d2": "reciprocal rank fusion combines rankings",
        "d3": "the culinary history of sourdough bread",
    }
    index.add((doc_id, embedder.embed([text])[0]) for doc_id, text in docs.items())

    query_vec = embedder.embed(["bm25 vector hybrid retrieval"])[0]
    results = index.search(query_vec, k=2)
    assert results[0][0] == "d1"
    assert len(results) == 2
