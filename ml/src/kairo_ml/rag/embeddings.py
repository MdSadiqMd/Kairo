"""Embedding providers

Defines the Embedder protocol plus two implementations:
- `HashEmbedder` — a deterministic, dependency-free bag-of-words embedder used
  in tests and offline. It produces stable pseudo-embeddings (the same text always
  maps to the same vector) without any model download, so retrieval logic can be
  exercised without a real embedding service.
- `BedrockEmbedder` — a production stub that lazily imports boto3 and calls
  an Amazon Bedrock embedding model. The import is deferred so this module loads
  offline with boto3 absent.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from kairo_ml.rag.bm25 import tokenize


class Embedder(Protocol):
    """Maps text to fixed-dimension dense vectors"""

    @property
    def dim(self) -> int: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; 0.0 when either vector has zero norm"""
    if len(a) != len(b):
        raise ValueError("vectors must have equal length")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class HashEmbedder:
    """Deterministic hashing embedder — stable vectors with no model

    Each token is hashed into one of dim buckets and a signed weight is added,
    giving a term-frequency-weighted signature. The sign (from a second hash bit)
    reduces collision cancellation bias. The vector is L2-normalized so cosine
    similarity reduces to a dot product. Identical text always yields an identical
    vector, which makes retrieval tests reproducible
    """

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        counts = Counter(tokenize(text))
        for token, count in counts.items():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign * count
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class BedrockEmbedder:
    """Amazon Bedrock embedding provider (lazy boto3 import)

    Not exercised in offline tests — boto3 and network access are unavailable
    there. The client is constructed on first use so importing this module never
    requires boto3
    """

    def __init__(
        self,
        model_id: str = "amazon.titan-embed-text-v2:0",
        *,
        region: str = "us-east-1",
        dim: int = 1024,
    ) -> None:
        self.model_id = model_id
        self.region = region
        self._dim = dim
        self._client: Any = None

    @property
    def dim(self) -> int:
        return self._dim

    def _ensure_client(self) -> Any:
        if self._client is None:
            import boto3  # lazy: keep boto3 off the default import path

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        import json

        client = self._ensure_client()
        vectors: list[list[float]] = []
        for text in texts:
            response = client.invoke_model(
                modelId=self.model_id,
                body=json.dumps({"inputText": text}),
            )
            payload = json.loads(response["body"].read())
            vectors.append([float(x) for x in payload["embedding"]])
        return vectors
