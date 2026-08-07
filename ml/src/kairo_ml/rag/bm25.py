"""Pure-Python Okapi BM25 lexical index

BM25 is the lexical half of hybrid retrieval; it catches exact-term and rare-term
matches that dense embeddings miss (identifiers, error codes, proper nouns). This
is a dependency-free implementation so it runs offline in tests and in any process
without pulling in a search engine

The scoring is standard Okapi BM25:

    score(D, Q) = sum over query terms qi of
        idf(qi) * ( f(qi, D) * (k1 + 1) )
                  / ( f(qi, D) + k1 * (1 - b + b * |D| / avgdl) )

where ``f(qi, D)`` is qi's frequency in document D, ``|D|`` is D's length in
tokens, ``avgdl`` is the mean document length, and

    idf(qi) = ln( 1 + (N - n(qi) + 0.5) / (n(qi) + 0.5) )

is the probabilistic IDF with the `1 +` guard that keeps it non-negative even
for terms appearing in most documents. `k1` controls term-frequency saturation;
`b` controls length normalization
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokenization shared across lexical components"""
    return _TOKEN.findall(text.lower())


class BM25Index:
    """Incremental Okapi BM25 index over string documents keyed by id"""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_ids: list[str] = []
        self._doc_tokens: list[list[str]] = []
        self._doc_freqs: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        # Document frequency: number of documents containing each term.
        self._doc_frequency: Counter[str] = Counter()

    def __len__(self) -> int:
        return len(self._doc_ids)

    def add(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        freqs = Counter(tokens)
        self._doc_ids.append(doc_id)
        self._doc_tokens.append(tokens)
        self._doc_freqs.append(freqs)
        self._doc_lengths.append(len(tokens))
        for term in freqs:
            self._doc_frequency[term] += 1

    def _avgdl(self) -> float:
        if not self._doc_lengths:
            return 0.0
        return sum(self._doc_lengths) / len(self._doc_lengths)

    def _idf(self, term: str) -> float:
        n_qi = self._doc_frequency.get(term, 0)
        total = len(self._doc_ids)
        return math.log(1.0 + (total - n_qi + 0.5) / (n_qi + 0.5))

    def score(self, query: str, doc_index: int) -> float:
        freqs = self._doc_freqs[doc_index]
        dl = self._doc_lengths[doc_index]
        avgdl = self._avgdl()
        if avgdl == 0.0:
            return 0.0
        total = 0.0
        for term in tokenize(query):
            f = freqs.get(term, 0)
            if f == 0:
                continue
            idf = self._idf(term)
            denom = f + self.k1 * (1.0 - self.b + self.b * dl / avgdl)
            total += idf * (f * (self.k1 + 1.0)) / denom
        return total

    def search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
        """Return the top-k `(doc_id, score)` pairs, highest score first

        Documents with a zero score (no query term present) are omitted so the
        fusion stage doesn't fuse noise
        """
        scored: list[tuple[str, float]] = []
        for i, doc_id in enumerate(self._doc_ids):
            s = self.score(query, i)
            if s > 0.0:
                scored.append((doc_id, s))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]
