from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from kairo_common.proofs import ProofJob

from kairo_ml.proofs.backends import ProofResult


class Risc0Backend:
    name = "risc0"

    SUPPORTED_KINDS = {"rl_reward_batch", "rl_filter", "rl_grpo", "rl_cycle", "eval_gate"}

    def __init__(self, host_bin: str = "", dev_mode: bool = False) -> None:
        self._host_bin = host_bin or os.environ.get("KAIRO_R0_HOST_BIN", "")
        self._dev_mode = dev_mode or os.environ.get("RISC0_DEV_MODE", "").lower() in ("1", "true")

    def supports(self, kind: str) -> bool:
        if not self._host_bin:
            return False
        if not Path(self._host_bin).exists():
            return False
        return kind in self.SUPPORTED_KINDS

    def prove(self, job: ProofJob, witness: dict) -> ProofResult:
        if not self.supports(job.kind):
            return ProofResult(
                status="unsupported", backend=self.name, error=f"kind {job.kind} not supported"
            )

        spec_hash = job.spec_hashes.get("combined", "")
        if not spec_hash:
            spec_hashes_list = sorted(job.spec_hashes.items())
            spec_hash = "|".join(f"{k}={v}" for k, v in spec_hashes_list)

        with tempfile.TemporaryDirectory() as tmpdir:
            witness_path = Path(tmpdir) / "witness.json"
            out_path = Path(tmpdir) / "proof.json"

            witness_path.write_text(json.dumps(witness))

            env = os.environ.copy()
            if self._dev_mode:
                env["RISC0_DEV_MODE"] = "1"

            try:
                result = subprocess.run(
                    [
                        self._host_bin,
                        "prove",
                        "--kind",
                        job.kind,
                        "--witness",
                        str(witness_path),
                        "--spec-hash",
                        spec_hash,
                        "--out",
                        str(out_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error="proof generation timed out after 600s",
                )
            except FileNotFoundError:
                return ProofResult(
                    status="unsupported",
                    backend=self.name,
                    error=f"host binary not found: {self._host_bin}",
                )

            if result.returncode != 0:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"prove failed: {result.stderr.strip() or result.stdout.strip()}",
                )

            if not out_path.exists():
                return ProofResult(
                    status="failed", backend=self.name, error="proof output not created"
                )

            proof_output = json.loads(out_path.read_text())
            receipt_path = proof_output.get("receipt_path", "")

            status = "dev_mode" if self._dev_mode else "verified"

            return ProofResult(
                status=status,
                backend=self.name,
                artifact_uri=receipt_path,
                journal_digest=proof_output.get("journal", ""),
                image_id=proof_output.get("image_id", ""),
            )

    def verify(self, kind: str, receipt_path: str) -> bool:
        if not self._host_bin or not Path(self._host_bin).exists():
            return False
        if not Path(receipt_path).exists():
            return False

        try:
            result = subprocess.run(
                [self._host_bin, "verify", "--kind", kind, "--receipt", receipt_path],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_image_id(self, kind: str) -> str | None:
        if not self._host_bin or not Path(self._host_bin).exists():
            return None
        try:
            result = subprocess.run(
                [self._host_bin, "image-id", "--kind", kind],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None
