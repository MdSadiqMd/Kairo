from __future__ import annotations

import time
from typing import Any

from kairo_common.ids import new_proof_id
from kairo_common.proofs import ProofJob

from kairo_ml.proofs.canonical import commit, commit_sequence, sha256_hex, to_fixed
from kairo_ml.proofs.fixedpoint import group_normalize_fixed
from kairo_ml.proofs.jobs import ProofJobSink
from kairo_ml.proofs.spec_hashes import (
    gate_spec_hash,
    grpo_spec_hash,
    lora_drift_spec_hash,
    rag_evidence_spec_hash,
    reward_spec_hash,
)


class LoraDriftBounds:
    """Specification for allowed LoRA adapter drift from base model

    These bounds define the trust region for adapter updates
    (Phase 5, Section 9 of the RL cryptography design):
    - max_l2_norm: maximum L2 norm across all adapter weight matrices
    - max_delta: maximum absolute change in any single weight element
    - max_rank: maximum rank for LoRA decomposition (r parameter)
    - allowed_modules: optional list of module name patterns the adapter may touch
    """

    def __init__(
        self,
        max_l2_norm: float = 10.0,
        max_delta: float = 1.0,
        max_rank: int = 64,
        allowed_modules: list[str] | None = None,
    ):
        self.max_l2_norm = max_l2_norm
        self.max_delta = max_delta
        self.max_rank = max_rank
        self.allowed_modules = allowed_modules

    def model_dump(self) -> dict:
        return {
            "max_l2_norm": self.max_l2_norm,
            "max_delta": self.max_delta,
            "max_rank": self.max_rank,
            "allowed_modules": self.allowed_modules,
        }


def commit_reward_batch(
    candidates: list[dict[str, Any]],
    stats: dict[str, int],
    *,
    run_id: str = "",
    sink: ProofJobSink | None = None,
) -> dict[str, str] | None:
    r_spec = reward_spec_hash()
    item_commitments: list[str] = []
    witness_items: list[dict] = []

    for c in candidates:
        prompt_sha = sha256_hex(c.get("prompt_raw", "").encode())
        output_sha = sha256_hex(c.get("output_raw", "").encode())
        reward_fp = to_fixed(c["reward"])
        reward_base_fp = to_fixed(c["reward_base"])

        item_doc = {
            "request_id": c.get("request_id", ""),
            "outcome": c.get("outcome", ""),
            "edit_persisted": c.get("edit_persisted", False),
            "followup_dissatisfaction": c.get("followup_dissatisfaction", False),
            "emitted_broken_tool_call": c.get("emitted_broken_tool_call", False),
            "deferred_via_clarifying_question": c.get("deferred_via_clarifying_question", False),
            "policy_step": c.get("policy_step", 0),
            "prompt_sha256": prompt_sha,
            "output_sha256": output_sha,
            "reward_fp": reward_fp,
            "reward_base_fp": reward_base_fp,
            "hacking_flags": list(c.get("hacking_flags", [])),
            "group_id": c.get("group_id", ""),
        }
        h = commit(item_doc)
        item_commitments.append(h)
        witness_items.append(item_doc)

        c["input_commitment"] = h
        c["reward_fp"] = reward_fp

    batch_commitment = commit_sequence(item_commitments) if item_commitments else ""
    proof_id = new_proof_id()

    result = {
        "batch_commitment": batch_commitment,
        "reward_spec_hash": r_spec,
        "proof_job_id": proof_id,
    }

    if sink is not None:
        job = ProofJob(
            proof_id=proof_id,
            kind="rl_reward_batch",
            subject_id=run_id or proof_id,
            spec_hashes={"reward": r_spec},
            commitments={"input_batch": batch_commitment},
            params={"item_count": len(candidates)},
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        witness = {
            "kind": "rl_reward_batch",
            "items": witness_items,
            "stats": stats,
            "reward_spec_hash": r_spec,
            "batch_commitment": batch_commitment,
        }
        sink.send(job, witness)

    return result


def commit_cycle(
    rollouts: list,
    result,
    *,
    policy_step: int,
    max_staleness: int,
    spec,
    baseline=None,
    sink: ProofJobSink | None = None,
) -> dict[str, str] | None:
    r_spec = reward_spec_hash()
    g_spec = grpo_spec_hash()
    g_spec_hash = gate_spec_hash(spec) if result.decision else ""

    def _rollout_commitment(r) -> str:
        return commit(
            {
                "request_id": r.request_id,
                "group_id": r.group_id,
                "reward_fp": to_fixed(r.reward),
                "policy_step": r.policy_step,
                "hacking_flags": list(r.hacking_flags),
            }
        )

    all_input = [_rollout_commitment(r) for r in rollouts]
    input_batch = commit_sequence(all_input) if all_input else ""

    kept_commits = [_rollout_commitment(r) for r in result.kept]
    kept_commitment = commit_sequence(kept_commits) if kept_commits else ""

    stale_commits = [_rollout_commitment(r) for r in result.dropped_stale]
    stale_commitment = commit_sequence(stale_commits) if stale_commits else ""

    hacking_commits = [_rollout_commitment(r) for r in result.dropped_hacking]
    hacking_commitment = commit_sequence(hacking_commits) if hacking_commits else ""

    if result.advantages:
        groups: dict[str, list[int]] = {}
        for r in result.kept:
            groups.setdefault(r.group_id, []).append(to_fixed(r.reward))
        fixed_advs: dict[str, list[int]] = {}
        for gid, rews in groups.items():
            fixed_advs[gid] = group_normalize_fixed(rews)
        adv_doc = {"groups": {k: v for k, v in sorted(fixed_advs.items())}}
        advantages_commitment = commit(adv_doc)
    else:
        advantages_commitment = ""

    eval_commitment = ""
    gate_commitment = ""
    if result.decision:
        checks_doc = [
            {"name": c.name, "passed": c.passed, "detail_sha256": sha256_hex(c.detail.encode())}
            for c in result.decision.checks
        ]
        gate_commitment = commit(
            {
                "promotable": result.decision.promotable,
                "checks": checks_doc,
            }
        )

    cycle_doc = {
        "input_batch": input_batch,
        "kept": kept_commitment,
        "dropped_stale": stale_commitment,
        "dropped_hacking": hacking_commitment,
        "advantages": advantages_commitment,
        "gate_decision": gate_commitment,
        "reward_spec_hash": r_spec,
        "grpo_spec_hash": g_spec,
        "gate_spec_hash": g_spec_hash,
        "policy_step": policy_step,
        "max_staleness": max_staleness,
        "accepted": result.accepted,
        "reason": result.reason,
    }
    cycle_commitment = commit(cycle_doc)

    proof_id = new_proof_id()
    fields = {
        "cycle_commitment": cycle_commitment,
        "proof_job_id": proof_id,
        "reward_spec_hash": r_spec,
        "grpo_spec_hash": g_spec,
    }
    if g_spec_hash:
        fields["gate_spec_hash"] = g_spec_hash

    if sink is not None:
        commitments = {
            "input_batch": input_batch,
            "kept": kept_commitment,
            "dropped_stale": stale_commitment,
            "dropped_hacking": hacking_commitment,
            "advantages": advantages_commitment,
            "gate_decision": gate_commitment,
            "cycle": cycle_commitment,
        }
        job = ProofJob(
            proof_id=proof_id,
            kind="rl_cycle",
            subject_id=f"cycle-step{policy_step}",
            spec_hashes={"reward": r_spec, "grpo": g_spec, "gate": g_spec_hash},
            commitments=commitments,
            params={"policy_step": policy_step, "max_staleness": max_staleness},
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        witness_rollouts = [
            {
                "request_id": r.request_id,
                "group_id": r.group_id,
                "reward": r.reward,
                "reward_fp": to_fixed(r.reward),
                "policy_step": r.policy_step,
                "hacking_flags": list(r.hacking_flags),
            }
            for r in rollouts
        ]
        witness = {
            "kind": "rl_cycle",
            "rollouts": witness_rollouts,
            "kept_indices": [i for i, r in enumerate(rollouts) if r in result.kept],
            "advantages": list(result.advantages),
            "policy_step": policy_step,
            "max_staleness": max_staleness,
            "accepted": result.accepted,
            "reason": result.reason,
            "commitments": commitments,
        }
        if result.decision:
            witness["gate_decision"] = {
                "promotable": result.decision.promotable,
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in result.decision.checks
                ],
            }
        sink.send(job, witness)

    return fields


def _eval_item_doc(item) -> dict:
    return {
        "item_id": item.item_id,
        "passed": item.passed,
        "score": to_fixed(item.score),
        "latency_ms": item.latency_ms,
        "cost_usd": to_fixed(item.cost_usd),
        "safety_flag": item.safety_flag,
    }


def _eval_item_float(item) -> dict:
    # Raw float fields so the proof worker can re-execute evaluate_gate exactly
    # (Python float arithmetic is deterministic and the bootstrap is seeded).
    # The verifier binds these to the fixed-point commitment via to_fixed.
    return {
        "item_id": item.item_id,
        "passed": item.passed,
        "score": item.score,
        "latency_ms": item.latency_ms,
        "cost_usd": item.cost_usd,
        "safety_flag": item.safety_flag,
    }


def commit_eval_run(
    run,
    decision,
    gate_spec,
    *,
    baseline=None,
    sink: ProofJobSink | None = None,
) -> dict[str, str] | None:
    g_hash = gate_spec_hash(gate_spec)
    item_commitments: list[str] = []
    witness_items: list[dict] = []

    for item in run.items:
        item_doc = _eval_item_doc(item)
        h = commit(item_doc)
        item_commitments.append(h)
        witness_items.append(item_doc)

    eval_run_commitment = commit_sequence(item_commitments) if item_commitments else ""

    baseline_commitment = ""
    baseline_items: list[dict] = []
    baseline_items_float: list[dict] = []
    if baseline is not None:
        baseline_items = [_eval_item_doc(i) for i in baseline.items]
        baseline_commits = [commit(d) for d in baseline_items]
        baseline_commitment = commit_sequence(baseline_commits) if baseline_commits else ""
        baseline_items_float = [_eval_item_float(i) for i in baseline.items]

    checks_doc = [
        {"name": c.name, "passed": c.passed, "detail_sha256": sha256_hex(c.detail.encode())}
        for c in decision.checks
    ]
    gate_commitment = commit(
        {
            "promotable": decision.promotable,
            "checks": checks_doc,
        }
    )

    proof_id = new_proof_id()
    fields = {
        "eval_run_commitment": eval_run_commitment,
        "gate_decision_commitment": gate_commitment,
        "gate_spec_hash": g_hash,
        "proof_job_id": proof_id,
    }

    if sink is not None:
        commitments = {"eval_run": eval_run_commitment, "gate_decision": gate_commitment}
        if baseline_commitment:
            commitments["baseline_run"] = baseline_commitment
        job = ProofJob(
            proof_id=proof_id,
            kind="eval_gate",
            subject_id=run.eval_run_id,
            spec_hashes={"gate": g_hash},
            commitments=commitments,
            params={"n": run.n},
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        witness = {
            "kind": "eval_gate",
            "eval_run_id": run.eval_run_id,
            "suite": run.suite,
            "model": run.model,
            "model_version": run.model_version,
            "items": witness_items,
            "items_float": [_eval_item_float(i) for i in run.items],
            "baseline_items": baseline_items,
            "baseline_items_float": baseline_items_float,
            "gate_spec": gate_spec.model_dump(),
            "gate_decision": {
                "promotable": decision.promotable,
                "checks": [
                    {"name": c.name, "passed": c.passed, "detail": c.detail}
                    for c in decision.checks
                ],
            },
            "gate_spec_hash": g_hash,
            "commitments": commitments,
        }
        sink.send(job, witness)

    return fields


def commit_rag_evidence(
    query_text: str,
    query_embedding_hash: str,
    retrieved_docs: list[dict[str, Any]],
    relevance_scores: list[float],
    *,
    corpus_snapshot_hash: str = "",
    grounding_passed: bool = False,
    grounding_threshold: float = 0.0,
    run_id: str = "",
    sink: ProofJobSink | None = None,
) -> dict[str, str] | None:
    """Commit RAG retrieval evidence for proof verification

    Creates a proof job that binds:
    - The query (by hash) to the retrieval results
    - Each retrieved document hash to its relevance score
    - The corpus snapshot to retrieved documents (membership proof)
    - The grounding decision to the threshold

    Args:
        query_text: The raw query text (hashed, not stored in witness)
        query_embedding_hash: Pre-computed hash of query embedding vector
        retrieved_docs: List of dicts with at least {"doc_id": str, "doc_hash": str}
        relevance_scores: Parallel list of relevance scores [0.0, 1.0]
        corpus_snapshot_hash: Hash of the corpus snapshot these docs came from
        grounding_passed: Whether the grounding threshold was met
        grounding_threshold: The threshold used for grounding decision
        run_id: Optional run identifier
        sink: Optional sink to send the proof job to

    Returns:
        Dict with commitment hashes and proof_job_id, or None on error
    """
    if len(retrieved_docs) != len(relevance_scores):
        raise ValueError(
            f"retrieved_docs length ({len(retrieved_docs)}) != "
            f"relevance_scores length ({len(relevance_scores)})"
        )

    rag_spec = rag_evidence_spec_hash()
    query_hash = sha256_hex(query_text.encode())

    doc_commitments: list[str] = []
    witness_docs: list[dict] = []

    for doc, score in zip(retrieved_docs, relevance_scores):
        if not 0.0 <= score <= 1.0:
            raise ValueError(f"relevance score {score} out of range [0.0, 1.0]")

        score_fp = to_fixed(score)
        doc_item = {
            "doc_id": doc.get("doc_id", ""),
            "doc_hash": doc.get("doc_hash", ""),
            "relevance_score_fp": score_fp,
        }
        h = commit(doc_item)
        doc_commitments.append(h)
        witness_docs.append(
            {
                "doc_id": doc.get("doc_id", ""),
                "doc_hash": doc.get("doc_hash", ""),
                "relevance_score": score,
                "relevance_score_fp": score_fp,
            }
        )

    docs_commitment = commit_sequence(doc_commitments) if doc_commitments else ""

    evidence_chain = {
        "query_hash": query_hash,
        "query_embedding_hash": query_embedding_hash,
        "docs_commitment": docs_commitment,
        "corpus_snapshot_hash": corpus_snapshot_hash,
        "grounding_passed": grounding_passed,
        "grounding_threshold_fp": to_fixed(grounding_threshold),
        "doc_count": len(retrieved_docs),
    }
    evidence_commitment = commit(evidence_chain)

    proof_id = new_proof_id()

    result = {
        "evidence_commitment": evidence_commitment,
        "docs_commitment": docs_commitment,
        "query_hash": query_hash,
        "rag_evidence_spec_hash": rag_spec,
        "proof_job_id": proof_id,
    }

    if sink is not None:
        commitments = {
            "evidence": evidence_commitment,
            "docs": docs_commitment,
        }
        job = ProofJob(
            proof_id=proof_id,
            kind="rag_evidence",
            subject_id=run_id or proof_id,
            spec_hashes={"rag_evidence": rag_spec},
            commitments=commitments,
            params={
                "doc_count": len(retrieved_docs),
                "grounding_passed": grounding_passed,
            },
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        witness = {
            "kind": "rag_evidence",
            "query_hash": query_hash,
            "query_embedding_hash": query_embedding_hash,
            "corpus_snapshot_hash": corpus_snapshot_hash,
            "docs": witness_docs,
            "grounding_passed": grounding_passed,
            "grounding_threshold": grounding_threshold,
            "grounding_threshold_fp": to_fixed(grounding_threshold),
            "rag_evidence_spec_hash": rag_spec,
            "commitments": commitments,
        }
        sink.send(job, witness)

    return result


class LoraDriftMetrics:
    """Computed drift metrics for an adapter relative to base model

    These are the actual measurements that get committed and verified:
    - l2_norm: total L2 norm of the adapter delta
    - max_delta: maximum absolute weight change
    - rank: effective rank of the adapter (LoRA r parameter or computed)
    - modified_modules: list of module names that were modified
    - num_params: number of trainable parameters in the adapter
    """

    def __init__(
        self,
        l2_norm: float,
        max_delta: float,
        rank: int,
        modified_modules: list[str],
        num_params: int = 0,
    ):
        self.l2_norm = l2_norm
        self.max_delta = max_delta
        self.rank = rank
        self.modified_modules = modified_modules
        self.num_params = num_params

    def within_bounds(self, bounds: LoraDriftBounds) -> bool:
        """Check if metrics satisfy the given bounds."""
        if self.l2_norm > bounds.max_l2_norm:
            return False
        if self.max_delta > bounds.max_delta:
            return False
        if self.rank > bounds.max_rank:
            return False
        if bounds.allowed_modules is not None:
            for mod in self.modified_modules:
                if not any(allowed in mod for allowed in bounds.allowed_modules):
                    return False
        return True


def commit_lora_drift(
    adapter_path: str,
    base_model_hash: str,
    adapter_hash: str,
    drift_metrics: LoraDriftMetrics,
    bounds: LoraDriftBounds,
    *,
    run_id: str = "",
    sink: ProofJobSink | None = None,
) -> dict[str, str] | None:
    """Commit a LoRA drift certificate for proof verification

    This creates a proof job that certifies the adapter weights haven't drifted
    beyond acceptable bounds from the base model (Phase 5 of the RL
    cryptography design)

    Args:
        adapter_path: filesystem or S3 path to the adapter weights
        base_model_hash: SHA256 hash of the base model weights
        adapter_hash: SHA256 hash of the adapter weights
        drift_metrics: computed drift metrics (L2 norm, max delta, rank, etc.)
        bounds: allowed bounds specification
        run_id: optional identifier for the training run
        sink: optional ProofJobSink to emit the proof job

    Returns:
        Dictionary with commitment hashes and proof job ID, or None if no sink
    """
    spec_hash = lora_drift_spec_hash(bounds)

    metrics_doc = {
        "l2_norm_fp": to_fixed(drift_metrics.l2_norm),
        "max_delta_fp": to_fixed(drift_metrics.max_delta),
        "rank": drift_metrics.rank,
        "modified_modules": sorted(drift_metrics.modified_modules),
        "num_params": drift_metrics.num_params,
    }
    metrics_commitment = commit(metrics_doc)

    certificate_doc = {
        "adapter_path_sha256": sha256_hex(adapter_path.encode()),
        "base_model_hash": base_model_hash,
        "adapter_hash": adapter_hash,
        "metrics": metrics_commitment,
        "spec_hash": spec_hash,
        "within_bounds": drift_metrics.within_bounds(bounds),
    }
    certificate_commitment = commit(certificate_doc)

    proof_id = new_proof_id()
    fields = {
        "certificate_commitment": certificate_commitment,
        "metrics_commitment": metrics_commitment,
        "spec_hash": spec_hash,
        "proof_job_id": proof_id,
        "within_bounds": drift_metrics.within_bounds(bounds),
    }

    if sink is not None:
        commitments = {
            "certificate": certificate_commitment,
            "metrics": metrics_commitment,
        }
        job = ProofJob(
            proof_id=proof_id,
            kind="lora_drift",
            subject_id=run_id or f"adapter-{adapter_hash[:12]}",
            spec_hashes={"lora_drift": spec_hash},
            commitments=commitments,
            params={
                "l2_norm_fp": to_fixed(drift_metrics.l2_norm),
                "max_delta_fp": to_fixed(drift_metrics.max_delta),
                "rank": drift_metrics.rank,
                "num_params": drift_metrics.num_params,
            },
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        witness = {
            "kind": "lora_drift",
            "adapter_path": adapter_path,
            "base_model_hash": base_model_hash,
            "adapter_hash": adapter_hash,
            "metrics": {
                "l2_norm": drift_metrics.l2_norm,
                "l2_norm_fp": to_fixed(drift_metrics.l2_norm),
                "max_delta": drift_metrics.max_delta,
                "max_delta_fp": to_fixed(drift_metrics.max_delta),
                "rank": drift_metrics.rank,
                "modified_modules": sorted(drift_metrics.modified_modules),
                "num_params": drift_metrics.num_params,
            },
            "bounds": bounds.model_dump(),
            "spec_hash": spec_hash,
            "within_bounds": drift_metrics.within_bounds(bounds),
            "commitments": commitments,
        }
        sink.send(job, witness)

    return fields
