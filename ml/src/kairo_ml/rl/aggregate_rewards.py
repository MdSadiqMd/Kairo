"""Batch reward aggregation job

Entry point for the ``reward-aggregator`` CronJob
(infra/kubernetes/rl/reward-aggregator.yaml). It reads redacted inference
events, computes the dense implicit reward for each, drops reward-hacking
suspects for audit, and writes scored training candidates for the fast on-policy
train -> per-cycle eval gate -> redeploy loop

Storage is pluggable: a local NDJSON reader/writer for dev and tests; S3 in
production (wired by the job's env). This module never performs a weight update
itself — that runs behind the eval gate (no ungated online updates)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from kairo_common import get_logger

from kairo_ml.rl.rewards import (
    InteractionSignals,
    compute_reward,
    outcome_from_feedback,
)

log = get_logger("reward-aggregator")


def iter_events(source: Iterable[str]) -> Iterator[dict[str, Any]]:
    for raw in source:
        line = raw.strip()
        if line:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping malformed event line")


def _group_id_from_prompt(prompt_raw: str) -> str:
    """Hash prompt to create a stable group id for GRPO advantage calculation."""
    return hashlib.sha256(prompt_raw.encode()).hexdigest()[:16]


def _infer_synthetic_feedback(event: dict[str, Any]) -> str | None:
    """Infer synthetic feedback for local testing when no explicit signal exists.

    In local/dev mode without a real feedback loop, we treat successful completions
    (finish_reason=stop, reasonable output length) as implicitly accepted. This
    lets the RL pipeline exercise the full flow without requiring a human-in-the-loop.
    """
    if event.get("user_feedback"):
        return event["user_feedback"]

    finish = event.get("finish_reason")
    output_tokens = event.get("output_tokens", 0)

    if finish == "stop" and output_tokens > 10:
        return "accepted"
    if finish == "content_filter":
        return "rejected"
    if finish == "length" and output_tokens > 50:
        return "accepted"
    return None


def score_event(
    event: dict[str, Any], *, synthetic_feedback: bool = False
) -> dict[str, Any] | None:
    """Return a scored training candidate, or None if the event is unusable."""
    if not event.get("training_consent"):
        return None
    prompt_raw = event.get("prompt_raw") or ""
    output_raw = event.get("output_raw") or ""
    if not prompt_raw or not output_raw:
        return None

    feedback = event.get("user_feedback")
    if synthetic_feedback and not feedback:
        feedback = _infer_synthetic_feedback(event)

    signals = InteractionSignals(
        outcome=outcome_from_feedback(feedback, event.get("finish_reason")),
        edit_persisted=bool(event.get("edit_persisted")),
        followup_dissatisfaction=bool(event.get("followup_dissatisfaction")),
        emitted_broken_tool_call=bool(event.get("emitted_broken_tool_call")),
        deferred_via_clarifying_question=bool(event.get("deferred_via_clarifying_question")),
    )
    breakdown = compute_reward(signals)
    return {
        "request_id": event.get("request_id"),
        "model_version": event.get("model_version"),
        "reward": breakdown.reward,
        "reward_base": breakdown.base,
        "hacking_flags": list(breakdown.hacking_flags),
        "group_id": _group_id_from_prompt(prompt_raw),
        "policy_step": event.get("policy_version", 0),
        "prompt_raw": prompt_raw,
        "output_raw": output_raw,
        # Raw signal fields are carried so the proof worker can re-execute
        # compute_reward on the committed witness (backends._verify_reward_batch).
        "outcome": signals.outcome,
        "edit_persisted": signals.edit_persisted,
        "followup_dissatisfaction": signals.followup_dissatisfaction,
        "emitted_broken_tool_call": signals.emitted_broken_tool_call,
        "deferred_via_clarifying_question": signals.deferred_via_clarifying_question,
    }


def aggregate(
    source: Iterable[str], *, synthetic_feedback: bool = False
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates: list[dict[str, Any]] = []
    stats = {"total": 0, "flagged": 0, "no_consent": 0, "no_text": 0}
    for event in iter_events(source):
        stats["total"] += 1
        if not event.get("training_consent"):
            stats["no_consent"] += 1
            continue
        scored = score_event(event, synthetic_feedback=synthetic_feedback)
        if scored is None:
            stats["no_text"] += 1
            continue
        if scored["hacking_flags"]:
            stats["flagged"] += 1
        candidates.append(scored)
    return candidates, stats


def _read_s3_ndjson(uri: str) -> list[str]:
    """Read all NDJSON files under an S3 prefix."""
    import boto3

    if not uri.startswith("s3://"):
        raise ValueError(f"expected s3:// URI, got {uri}")
    parts = uri[5:].split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""

    s3 = boto3.client("s3")
    lines: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".ndjson") or key.endswith(".jsonl"):
                resp = s3.get_object(Bucket=bucket, Key=key)
                body = resp["Body"].read().decode("utf-8")
                lines.extend(body.strip().split("\n"))
    return lines


def _write_s3_ndjson(uri: str, lines: list[str]) -> None:
    """Write NDJSON to an S3 object."""
    import boto3

    if not uri.startswith("s3://"):
        raise ValueError(f"expected s3:// URI, got {uri}")
    parts = uri[5:].split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else "output.ndjson"

    s3 = boto3.client("s3")
    body = "\n".join(lines) + "\n"
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aggregate_rewards")
    parser.add_argument(
        "--input",
        default=os.environ.get("AGGREGATOR_INPUT_URI", ""),
        help="S3 URI (s3://bucket/prefix) or local path to redacted events.",
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("AGGREGATOR_OUTPUT_URI", ""),
        help="S3 URI or local path for scored candidates NDJSON.",
    )
    parser.add_argument(
        "--synthetic-feedback",
        action="store_true",
        default=os.environ.get("AGGREGATOR_SYNTHETIC_FEEDBACK", "").lower() in ("1", "true"),
        help="Infer synthetic feedback for local testing (env: AGGREGATOR_SYNTHETIC_FEEDBACK).",
    )
    args = parser.parse_args(argv)

    input_uri = args.input
    output_uri = args.output

    if input_uri.startswith("s3://"):
        source = _read_s3_ndjson(input_uri)
    elif input_uri:
        source = Path(input_uri).read_text().splitlines()
    else:
        source = sys.stdin

    candidates, stats = aggregate(source, synthetic_feedback=args.synthetic_feedback)

    from kairo_ml.proofs.settings import zk_enabled

    if zk_enabled():
        from kairo_ml.proofs import witness
        from kairo_ml.proofs.jobs import DirProofJobSink, SqsProofJobSink

        queue_url = os.environ.get("PROOF_QUEUE_URL", "")
        artifacts_uri = os.environ.get("PROOF_ARTIFACTS_URI", "")
        if queue_url:
            sink = SqsProofJobSink(queue_url, artifacts_uri)
        else:
            proof_dir = os.environ.get("PROOF_QUEUE_DIR", "/tmp/proof-jobs")
            sink = DirProofJobSink(proof_dir)
        batch_ref = witness.commit_reward_batch(candidates, stats, run_id=input_uri, sink=sink)
        if batch_ref:
            log.info("zk reward batch committed", extra=batch_ref)

    out_lines = [json.dumps(c) for c in candidates]

    if output_uri.startswith("s3://"):
        _write_s3_ndjson(output_uri, out_lines)
    elif output_uri:
        Path(output_uri).write_text("\n".join(out_lines) + "\n")
    else:
        for line in out_lines:
            print(line)

    log.info(
        "reward aggregation complete",
        extra={"candidates": len(candidates), **stats},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
