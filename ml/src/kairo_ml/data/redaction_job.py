"""Batch redaction job

Entry point for the redaction CronJob. Reads raw inference events from S3,
applies the redaction pipeline, and writes redacted events to the training-
eligible bucket. Events that fail consent/license checks are dropped

    python -m kairo_ml.data.redaction_job \
        --input s3://bucket/raw-events/2026/07/14/ \
        --output s3://bucket/redacted-events/2026/07/14/

Respects AWS_ENDPOINT_URL for local development with MiniStack
"""

from __future__ import annotations

import argparse
import json
import os

from kairo_common import configure_logging, get_logger

from kairo_ml.data.redaction import RedactionPipeline, TenantPolicy

log = get_logger("redaction-job")


def _get_s3_client():
    import boto3

    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    return boto3.client("s3", endpoint_url=endpoint_url)


def _list_objects(bucket: str, prefix: str) -> list[str]:
    s3 = _get_s3_client()
    keys: list[str] = []
    kwargs = {"Bucket": bucket, "Prefix": prefix}
    while True:
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents", []):
            if obj["Key"].endswith(".ndjson") or obj["Key"].endswith(".jsonl"):
                keys.append(obj["Key"])
        if not resp.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = resp["NextContinuationToken"]
    return keys


def _read_jsonl(bucket: str, key: str) -> list[dict]:
    s3 = _get_s3_client()
    response = s3.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def _write_jsonl(bucket: str, key: str, records: list[dict]) -> None:
    s3 = _get_s3_client()
    body = "\n".join(json.dumps(r) for r in records) + "\n"
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parts = uri.removeprefix("s3://").split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def run_redaction(input_uri: str, output_uri: str) -> dict:
    in_bucket, in_prefix = _parse_s3_uri(input_uri)
    out_bucket, out_prefix = _parse_s3_uri(output_uri)

    policy = TenantPolicy(
        training_opt_in=os.environ.get("REDACTION_TRAINING_OPT_IN", "true").lower() == "true",
    )
    pipeline = RedactionPipeline(policy)

    stats = {"files": 0, "events": 0, "dropped": 0, "pii_removed": 0, "secrets_removed": 0}
    keys = _list_objects(in_bucket, in_prefix)
    log.info("starting redaction", extra={"files": len(keys), "input": input_uri})

    for key in keys:
        events = _read_jsonl(in_bucket, key)
        redacted_events: list[dict] = []

        for event in events:
            stats["events"] += 1
            redacted, report = pipeline.process(event)
            if redacted is None:
                stats["dropped"] += 1
            else:
                stats["pii_removed"] += report.pii_removed
                stats["secrets_removed"] += report.secrets_removed
                redacted_events.append(redacted)

        if redacted_events:
            rel_key = key.removeprefix(in_prefix).lstrip("/")
            out_key = f"{out_prefix}/{rel_key}".replace("//", "/")
            _write_jsonl(out_bucket, out_key, redacted_events)
            stats["files"] += 1

    log.info("redaction complete", extra=stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    configure_logging("redaction-job")
    parser = argparse.ArgumentParser(prog="redaction-job")
    parser.add_argument("--input", required=True, help="S3 URI for raw events (prefix)")
    parser.add_argument("--output", required=True, help="S3 URI for redacted events (prefix)")
    args = parser.parse_args(argv)

    stats = run_redaction(args.input, args.output)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
