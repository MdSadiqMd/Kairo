from __future__ import annotations

from kairo_ml.data.manifests import (
    build_manifest,
    check_contamination,
    content_hash,
    dedupe,
    minhash_similarity,
)
from kairo_ml.data.redaction import (
    RedactionPipeline,
    RedactionReport,
    TenantPolicy,
    redact_text,
    shannon_entropy,
)


def test_redact_removes_pii_and_secrets() -> None:
    report = RedactionReport()
    text = "email me at jane@example.com or call 415-555-1234, key AKIA1234567890ABCDEF"
    out = redact_text(text, report)
    assert "jane@example.com" not in out
    assert "415-555-1234" not in out
    assert "AKIA1234567890ABCDEF" not in out
    assert report.pii_removed >= 2
    assert report.secrets_removed >= 1


def test_high_entropy_token_is_redacted() -> None:
    report = RedactionReport()
    secret = "Zx9Kp2Lq8Wm4Rt6Yn0Bv3Cs7Df1Gh5"  # high-entropy
    out = redact_text(f"token={secret}", report)
    assert secret not in out
    assert shannon_entropy(secret) > 3.5


def test_pipeline_drops_without_consent() -> None:
    pipe = RedactionPipeline(TenantPolicy(training_opt_in=True))
    event = {"training_consent": False, "prompt_raw": "hello"}
    redacted, report = pipe.process(event)
    assert redacted is None
    assert report.dropped and report.drop_reason == "no_training_consent"


def test_pipeline_redacts_with_consent() -> None:
    pipe = RedactionPipeline(TenantPolicy(training_opt_in=True))
    event = {"training_consent": True, "prompt_raw": "mail jane@example.com"}
    redacted, _report = pipe.process(event)
    assert redacted is not None
    assert "jane@example.com" not in redacted["prompt_raw"]


def test_pipeline_drops_disallowed_license() -> None:
    pipe = RedactionPipeline(TenantPolicy(training_opt_in=True))
    event = {"training_consent": True, "license": "gpl-3.0", "prompt_raw": "x"}
    redacted, report = pipe.process(event)
    assert redacted is None
    assert report.drop_reason.startswith("license_not_allowed")


def test_dedupe_removes_exact_and_near_duplicates() -> None:
    records = [
        "the quick brown fox jumps over the lazy dog",
        "the quick brown fox jumps over the lazy dog",  # exact dup
        "the quick brown fox jumps over the lazy dog today",  # near dup
        "completely different sentence about databases and indexes",
    ]
    result = dedupe(records, near_threshold=0.6)
    assert result.exact_duplicates == 1
    assert result.near_duplicates >= 1
    assert len(result.kept) == 2


def test_contamination_detects_ngram_overlap_and_canary() -> None:
    training = (
        "the mitochondria is the powerhouse of the cell and it produces atp for energy use daily"
    )
    evals = {"bio_eval": [training]}  # identical → strong overlap
    hits = check_contamination(training, evals, n=13, canaries=["CANARY-XYZ"])
    assert hits and hits[0].matched_ngrams > 0

    with_canary = training + " CANARY-XYZ"
    hits2 = check_contamination(
        with_canary, {"e": ["unrelated text here"]}, canaries=["CANARY-XYZ"]
    )
    assert hits2 and hits2[0].canary_hits == 1


def test_build_manifest_records_evidence() -> None:
    records = ["alpha beta gamma", "alpha beta gamma", "delta epsilon zeta"]
    kept, manifest = build_manifest(
        "ds1",
        "2026-07-11T00:00:00Z",
        records,
        source_uris=["s3://x"],
        eval_corpora={"e": ["alpha beta gamma"]},
    )
    assert manifest.record_count == len(kept) == 2
    assert manifest.exact_duplicates_removed == 1
    assert manifest.dedupe_hash == content_hash("\n".join(sorted(content_hash(r) for r in kept)))
    assert "e" in manifest.contamination_checks


def test_minhash_similarity_high_for_similar() -> None:
    a = "the quick brown fox jumps over the lazy dog"
    b = "the quick brown fox jumps over the lazy dog now"
    assert minhash_similarity(a, b) > 0.5
    assert minhash_similarity(a, "totally unrelated content") < 0.3
