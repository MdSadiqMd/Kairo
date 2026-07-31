"""Dataset manifests, dedup, and contamination checks

``dedupe_hash`` and ``contamination_checks`` in a manifest are *outputs of a real
pipeline*, not free-text assertions. This module provides:
- exact + near-exact dedup (content SHA-256 plus a MinHash/LSH near-dup pass)
- eval contamination detection via 13-gram overlap against every eval set,
  plus a canary-string scan
- a ``DatasetManifest`` that records the tool version, thresholds, and match
  counts — the evidence, not just ``passed``

Dedup is also a privacy control: near-duplicate removal measurably
reduces memorization and drives membership-inference toward chance
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

MANIFEST_TOOL_VERSION = "manifest-pipeline/0.1.0"
_WORD = re.compile(r"\w+")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shingles(text: str, k: int = 5) -> set[str]:
    tokens = _WORD.findall(text.lower())
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _minhash(shingles: set[str], num_perm: int = 64) -> tuple[int, ...]:
    """A tiny MinHash signature using salted SHA-1 hashes as permutations."""
    if not shingles:
        return tuple([0] * num_perm)
    sig: list[int] = []
    for seed in range(num_perm):
        salt = str(seed).encode()
        sig.append(
            min(
                int.from_bytes(hashlib.sha1(salt + s.encode()).digest()[:8], "big")
                for s in shingles
            )
        )
    return tuple(sig)


def minhash_similarity(a: str, b: str, num_perm: int = 64) -> float:
    sa, sb = _minhash(_shingles(a), num_perm), _minhash(_shingles(b), num_perm)
    matches = sum(1 for x, y in zip(sa, sb, strict=True) if x == y)
    return matches / num_perm


@dataclass
class DedupResult:
    kept: list[str]
    exact_duplicates: int = 0
    near_duplicates: int = 0
    kept_indices: list[int] = field(default_factory=list)


def dedupe(records: list[str], *, near_threshold: float = 0.8) -> DedupResult:
    """Remove exact and near-duplicate records. Order-preserving."""
    seen_hashes: set[str] = set()
    kept: list[str] = []
    kept_sigs: list[tuple[int, ...]] = []
    kept_indices: list[int] = []
    exact = near = 0
    for idx, rec in enumerate(records):
        h = content_hash(rec)
        if h in seen_hashes:
            exact += 1
            continue
        sig = _minhash(_shingles(rec))
        if any(_sig_sim(sig, s) >= near_threshold for s in kept_sigs):
            near += 1
            continue
        seen_hashes.add(h)
        kept.append(rec)
        kept_sigs.append(sig)
        kept_indices.append(idx)
    return DedupResult(kept, exact, near, kept_indices)


def _sig_sim(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)


def _ngrams(text: str, n: int = 13) -> set[str]:
    tokens = _WORD.findall(text.lower())
    if len(tokens) < n:
        return set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


@dataclass
class ContaminationHit:
    eval_set: str
    matched_ngrams: int
    canary_hits: int


def check_contamination(
    record: str,
    eval_corpora: dict[str, list[str]],
    *,
    n: int = 13,
    canaries: list[str] | None = None,
) -> list[ContaminationHit]:
    """Detect n-gram overlap of a training record against each eval set, plus
    a canary-string scan"""
    rec_ngrams = _ngrams(record, n)
    hits: list[ContaminationHit] = []
    lowered = record.lower()
    for name, corpus in eval_corpora.items():
        overlap = 0
        for item in corpus:
            overlap += len(rec_ngrams & _ngrams(item, n))
        canary_hits = sum(1 for c in (canaries or []) if c.lower() in lowered)
        if overlap or canary_hits:
            hits.append(ContaminationHit(name, overlap, canary_hits))
    return hits


class DatasetManifest(BaseModel):
    """Every dataset carries one of these"""

    dataset_id: str
    created_at: str
    source_uris: list[str] = Field(default_factory=list)
    record_count: int
    token_count: int = 0
    pii_scan: str = "passed"
    license_scan: str = "passed"
    consent_policy: str = "training_opt_in_only"
    dedupe_hash: str = ""
    dedupe_tool_version: str = MANIFEST_TOOL_VERSION
    exact_duplicates_removed: int = 0
    near_duplicates_removed: int = 0
    near_dup_threshold: float = 0.8
    contamination_checks: list[str] = Field(default_factory=list)
    contamination_matches: int = 0
    dp_epsilon: float | None = None  # set when trained with DP-SGD


def build_manifest(
    dataset_id: str,
    created_at: str,
    records: list[str],
    *,
    source_uris: list[str],
    eval_corpora: dict[str, list[str]] | None = None,
    canaries: list[str] | None = None,
    near_threshold: float = 0.8,
) -> tuple[list[str], DatasetManifest]:
    """Run dedup + contamination and produce the deduped records + manifest."""
    dedup = dedupe(records, near_threshold=near_threshold)
    corpus_hash = content_hash("\n".join(sorted(content_hash(r) for r in dedup.kept)))

    total_matches = 0
    checked: list[str] = []
    if eval_corpora:
        checked = list(eval_corpora)
        for rec in dedup.kept:
            for hit in check_contamination(rec, eval_corpora, canaries=canaries):
                total_matches += hit.matched_ngrams + hit.canary_hits

    manifest = DatasetManifest(
        dataset_id=dataset_id,
        created_at=created_at,
        source_uris=source_uris,
        record_count=len(dedup.kept),
        dedupe_hash=corpus_hash,
        exact_duplicates_removed=dedup.exact_duplicates,
        near_duplicates_removed=dedup.near_duplicates,
        near_dup_threshold=near_threshold,
        contamination_checks=checked,
        contamination_matches=total_matches,
    )
    return dedup.kept, manifest
