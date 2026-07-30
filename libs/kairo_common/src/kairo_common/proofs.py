from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

ProofStatus = Literal[
    "pending",
    "attested",
    "dev_mode",
    "verified",
    "failed",
    "skipped",
    "unsupported",
]

ProofKind = Literal[
    "rl_reward_batch",
    "rl_cycle",
    "eval_gate",
    "rag_evidence",
    "lora_drift",
]


class ProofReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proof_id: str
    kind: ProofKind
    subject_id: str
    status: ProofStatus
    backend: str | None = None
    zk_inference: bool = True
    commitments: dict[str, str] = {}
    spec_hashes: dict[str, str] = {}
    journal_digest: str | None = None
    artifact_uri: str | None = None
    error: str | None = None
    created_at: str
    proved_at: str | None = None
    verified_at: str | None = None


class ProofJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proof_id: str
    kind: ProofKind
    subject_id: str
    profile_id: str = "default"
    zk_inference: bool = True
    spec_hashes: dict[str, str] = {}
    commitments: dict[str, str] = {}
    params: dict[str, int | float | str | bool] = {}
    witness_uri: str = ""
    receipt_uri: str = ""
    created_at: str = ""
