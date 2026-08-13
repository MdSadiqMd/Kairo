from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kairo_common.proofs import ProofJob


class ProofJobSink(Protocol):
    def send(self, job: ProofJob, witness: dict) -> None: ...


@dataclass(frozen=True)
class ProofJobMessage:
    proof_id: str
    body: str
    handle: str


class ProofJobQueue(Protocol):
    def poll(self) -> ProofJobMessage | None: ...
    def ack(self, message: ProofJobMessage) -> None: ...


class DirProofJobSink:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._witness_dir = self._dir / "witnesses"
        self._witness_dir.mkdir(exist_ok=True)

    def send(self, job: ProofJob, witness: dict) -> None:
        witness_path = self._witness_dir / f"{job.proof_id}.json"
        witness_path.write_text(json.dumps(witness, sort_keys=True))
        job_copy = job.model_copy(update={"witness_uri": f"file://{witness_path}"})
        (self._dir / f"{job.proof_id}.json").write_text(job_copy.model_dump_json())


class DirProofJobQueue:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._done = self._dir / "done"
        self._done.mkdir(exist_ok=True)

    def poll(self) -> ProofJobMessage | None:
        for path in sorted(self._dir.glob("proof_*.json")):
            data = json.loads(path.read_text())
            return ProofJobMessage(
                proof_id=data["proof_id"],
                body=path.read_text(),
                handle=str(path),
            )
        return None

    def ack(self, message: ProofJobMessage) -> None:
        src = Path(message.handle)
        if src.exists():
            src.rename(self._done / src.name)


class SqsProofJobSink:
    def __init__(self, queue_url: str, artifacts_uri: str = "") -> None:
        self._queue_url = queue_url
        self._artifacts_uri = artifacts_uri.rstrip("/")

    def send(self, job: ProofJob, witness: dict) -> None:
        import boto3

        s3 = boto3.client("s3")
        witness_key = f"proofs/witness/{job.kind}/{job.proof_id}.json"
        bucket = (
            self._artifacts_uri.removeprefix("s3://").split("/")[0] if self._artifacts_uri else ""
        )
        if bucket:
            s3.put_object(
                Bucket=bucket,
                Key=witness_key,
                Body=json.dumps(witness, sort_keys=True).encode(),
            )
            witness_uri = f"s3://{bucket}/{witness_key}"
        else:
            witness_uri = ""

        job_copy = job.model_copy(update={"witness_uri": witness_uri})
        sqs = boto3.client("sqs")
        sqs.send_message(QueueUrl=self._queue_url, MessageBody=job_copy.model_dump_json())


class SqsProofJobQueue:
    def __init__(self, queue_url: str) -> None:
        self._queue_url = queue_url

    def poll(self) -> ProofJobMessage | None:
        import boto3

        sqs = boto3.client("sqs")
        resp = sqs.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=10,
        )
        messages = resp.get("Messages", [])
        if not messages:
            return None
        msg = messages[0]
        body = msg["Body"]
        data = json.loads(body)
        return ProofJobMessage(
            proof_id=data.get("proof_id", ""),
            body=body,
            handle=msg["ReceiptHandle"],
        )

    def ack(self, message: ProofJobMessage) -> None:
        import boto3

        sqs = boto3.client("sqs")
        sqs.delete_message(QueueUrl=self._queue_url, ReceiptHandle=message.handle)
