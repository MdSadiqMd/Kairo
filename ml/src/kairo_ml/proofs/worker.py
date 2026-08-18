from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from kairo_common import get_logger
from kairo_common.proofs import ProofReceipt

from kairo_ml.proofs.backends import HashCommitBackend, ProofBackend
from kairo_ml.proofs.jobs import DirProofJobQueue, ProofJobMessage, ProofJobQueue
from kairo_ml.proofs.receipts import FileReceiptStore, ReceiptStore

logger = get_logger("proof-worker")


@dataclass
class ProofWorkerConfig:
    poll_interval_s: float = 2.0


class ProofWorker:
    def __init__(
        self,
        *,
        queue: ProofJobQueue,
        backends: Sequence[ProofBackend],
        receipts: ReceiptStore,
        config: ProofWorkerConfig | None = None,
    ) -> None:
        self._queue = queue
        self._backends = list(backends)
        self._receipts = receipts
        self._config = config or ProofWorkerConfig()

    def run_one(self, message: ProofJobMessage) -> str:
        from kairo_common.proofs import ProofJob

        job = ProofJob.model_validate_json(message.body)

        existing = self._receipts.get(job.proof_id)
        if existing and existing.status in ("attested", "verified", "dev_mode"):
            return existing.status

        receipt = ProofReceipt(
            proof_id=job.proof_id,
            kind=job.kind,
            subject_id=job.subject_id,
            status="pending",
            backend=None,
            zk_inference=job.zk_inference,
            commitments=job.commitments,
            spec_hashes=job.spec_hashes,
            created_at=job.created_at,
        )
        self._receipts.put(receipt)

        witness = self._load_witness(job.witness_uri)

        best_status = "unsupported"
        best_result = None
        for backend in self._backends:
            if not backend.supports(job.kind):
                continue
            result = backend.prove(job, witness)
            if result.status in ("attested", "verified", "dev_mode"):
                best_status = result.status
                best_result = result
                break
            if result.status == "failed":
                best_status = "failed"
                best_result = result
                break

        proved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        extra: dict[str, str] = {"proved_at": proved_at}
        if best_result:
            if best_result.backend:
                extra["backend"] = best_result.backend
            if best_result.error:
                extra["error"] = best_result.error
            if best_result.artifact_uri:
                extra["artifact_uri"] = best_result.artifact_uri
            if best_result.journal_digest:
                extra["journal_digest"] = best_result.journal_digest
            if best_result.image_id:
                extra["image_id"] = best_result.image_id
        self._receipts.update_status(job.proof_id, best_status, **extra)

        return best_status

    def _load_witness(self, uri: str) -> dict:
        if uri.startswith("file://"):
            return json.loads(Path(uri.removeprefix("file://")).read_text())
        if uri.startswith("s3://"):
            import boto3

            parts = uri.removeprefix("s3://").split("/", 1)
            obj = boto3.client("s3").get_object(Bucket=parts[0], Key=parts[1])
            return json.loads(obj["Body"].read())
        return {}

    def serve(self, *, should_stop: Callable[[], bool], max_iterations: int | None = None) -> int:
        processed = 0
        iterations = 0
        while not should_stop():
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            message = self._queue.poll()
            if message is None:
                if max_iterations is not None:
                    continue
                time.sleep(self._config.poll_interval_s)
                continue
            logger.info("proof worker picked up job", extra={"proof_id": message.proof_id})
            status = self.run_one(message)
            self._queue.ack(message)
            processed += 1
            logger.info(
                "proof worker finished job", extra={"proof_id": message.proof_id, "status": status}
            )
        return processed


def main() -> int:
    from kairo_ml.proofs.settings import zk_enabled

    if not zk_enabled():
        logger.info("ZK_INFERENCE disabled, proof worker exiting")
        return 0

    queue_url = os.environ.get("PROOF_QUEUE_URL", "")
    queue_dir = os.environ.get("PROOF_QUEUE_DIR", "")
    receipts_table = os.environ.get("PROOF_RECEIPTS_TABLE", "")
    receipts_dir = os.environ.get("PROOF_RECEIPTS_DIR", "/tmp/proof-receipts")

    if queue_dir:
        queue: ProofJobQueue = DirProofJobQueue(queue_dir)
    elif queue_url:
        from kairo_ml.proofs.jobs import SqsProofJobQueue

        queue = SqsProofJobQueue(queue_url)
    else:
        logger.error("no queue configured (set PROOF_QUEUE_URL or PROOF_QUEUE_DIR)")
        return 1

    if receipts_table:
        from kairo_ml.proofs.receipts import DynamoReceiptStore

        receipts: ReceiptStore = DynamoReceiptStore(receipts_table)
    else:
        receipts = FileReceiptStore(receipts_dir)

    backends: list[ProofBackend] = [HashCommitBackend()]

    host_bin = os.environ.get("KAIRO_R0_HOST_BIN", "")
    dev_mode = os.environ.get("RISC0_DEV_MODE", "").lower() in ("1", "true")
    if host_bin:
        from kairo_ml.proofs.risc0 import Risc0Backend

        backends.append(Risc0Backend(host_bin=host_bin, dev_mode=dev_mode))

    worker = ProofWorker(queue=queue, backends=backends, receipts=receipts)

    import signal

    stop = False

    def _handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("proof worker starting")
    processed = worker.serve(should_stop=lambda: stop)
    logger.info("proof worker stopped", extra={"processed": processed})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
