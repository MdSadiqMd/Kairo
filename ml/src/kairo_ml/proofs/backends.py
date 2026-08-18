from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kairo_common.proofs import ProofJob, ProofStatus

from kairo_ml.proofs.canonical import commit, commit_sequence, sha256_hex, to_fixed
from kairo_ml.proofs.fixedpoint import group_normalize_fixed
from kairo_ml.proofs.spec_hashes import (
    gate_spec_hash,
    grpo_spec_hash,
    lora_drift_spec_hash,
    rag_evidence_spec_hash,
    reward_spec_hash,
)
from kairo_ml.proofs.witness import LoraDriftBounds, LoraDriftMetrics


@dataclass(frozen=True)
class ProofResult:
    status: ProofStatus
    backend: str
    journal_digest: str | None = None
    artifact_uri: str | None = None
    artifact: bytes | None = None
    image_id: str | None = None
    error: str | None = None


class ProofBackend(Protocol):
    name: str

    def supports(self, kind: str) -> bool: ...
    def prove(self, job: ProofJob, witness: dict) -> ProofResult: ...


class HashCommitBackend:
    name = "hash-commit"

    def supports(self, kind: str) -> bool:
        return kind in ("rl_reward_batch", "rl_cycle", "eval_gate", "rag_evidence", "lora_drift")

    def prove(self, job: ProofJob, witness: dict) -> ProofResult:
        try:
            kind = job.kind
            if kind == "rl_reward_batch":
                return self._verify_reward_batch(job, witness)
            elif kind == "rl_cycle":
                return self._verify_cycle(job, witness)
            elif kind == "eval_gate":
                return self._verify_eval_gate(job, witness)
            elif kind == "rag_evidence":
                return self._verify_rag_evidence(job, witness)
            elif kind == "lora_drift":
                return self._verify_lora_drift(job, witness)
            return ProofResult(
                status="unsupported", backend=self.name, error=f"unknown kind {kind}"
            )
        except Exception as exc:
            return ProofResult(status="failed", backend=self.name, error=str(exc))

    def _verify_reward_batch(self, job: ProofJob, witness: dict) -> ProofResult:
        from kairo_ml.rl.rewards import InteractionSignals, compute_reward

        items = witness.get("items", [])
        recomputed: list[str] = []

        for item in items:
            sig = InteractionSignals(
                outcome=item.get("outcome", "shown_no_action"),
                edit_persisted=item.get("edit_persisted", False),
                followup_dissatisfaction=item.get("followup_dissatisfaction", False),
                emitted_broken_tool_call=item.get("emitted_broken_tool_call", False),
                deferred_via_clarifying_question=item.get(
                    "deferred_via_clarifying_question", False
                ),
            )
            bd = compute_reward(sig)
            expected_reward_fp = to_fixed(bd.reward)
            if expected_reward_fp != item["reward_fp"]:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"reward_fp mismatch for {item.get('request_id')}: "
                    f"recomputed {expected_reward_fp} != witness {item['reward_fp']}",
                )
            h = commit(item)
            recomputed.append(h)

        batch = commit_sequence(recomputed) if recomputed else ""
        if batch != job.commitments.get("input_batch", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"batch_commitment mismatch: recomputed {batch}",
            )

        if job.spec_hashes.get("reward") != reward_spec_hash():
            return ProofResult(
                status="failed",
                backend=self.name,
                error="reward_spec_hash mismatch",
            )

        return ProofResult(status="attested", backend=self.name)

    def _verify_cycle(self, job: ProofJob, witness: dict) -> ProofResult:
        # Re-executes the filter + GRPO advantage math on the committed witness
        # produced by witness.commit_cycle and recomputes every commitment in the
        # cycle receipt chain. Any divergence names the field that moved.
        if job.spec_hashes.get("reward") != reward_spec_hash():
            return ProofResult(
                status="failed", backend=self.name, error="reward_spec_hash mismatch"
            )
        if job.spec_hashes.get("grpo") != grpo_spec_hash():
            return ProofResult(status="failed", backend=self.name, error="grpo_spec_hash mismatch")

        rollouts = witness.get("rollouts", [])
        policy_step = witness.get("policy_step", 0)
        max_staleness = witness.get("max_staleness", 0)

        def rollout_commitment(r: dict) -> str:
            return commit(
                {
                    "request_id": r.get("request_id", ""),
                    "group_id": r.get("group_id", ""),
                    "reward_fp": r.get("reward_fp", 0),
                    "policy_step": r.get("policy_step", 0),
                    "hacking_flags": list(r.get("hacking_flags", [])),
                }
            )

        kept: list[dict] = []
        stale: list[dict] = []
        hacking: list[dict] = []
        for r in rollouts:
            # Mirrors OnlineRLLoop.filter_rollouts: hacking discard takes
            # priority over the staleness guard.
            if r.get("hacking_flags"):
                hacking.append(r)
            elif policy_step - r.get("policy_step", 0) > max_staleness:
                stale.append(r)
            else:
                kept.append(r)

        all_commits = [rollout_commitment(r) for r in rollouts]
        input_batch = commit_sequence(all_commits) if all_commits else ""
        if input_batch != job.commitments.get("input_batch", ""):
            return ProofResult(
                status="failed", backend=self.name, error="input_batch commitment mismatch"
            )

        for name, subset in (
            ("kept", kept),
            ("dropped_stale", stale),
            ("dropped_hacking", hacking),
        ):
            commits = [rollout_commitment(r) for r in subset]
            recomputed = commit_sequence(commits) if commits else ""
            if recomputed != job.commitments.get(name, ""):
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"{name} commitment mismatch: filter re-execution diverged",
                )

        claimed_advantages = job.commitments.get("advantages", "")
        if claimed_advantages:
            groups: dict[str, list[int]] = {}
            for r in kept:
                groups.setdefault(r.get("group_id", ""), []).append(r.get("reward_fp", 0))
            fixed_advs = {gid: group_normalize_fixed(rews) for gid, rews in groups.items()}
            adv_doc = {"groups": {k: v for k, v in sorted(fixed_advs.items())}}
            if commit(adv_doc) != claimed_advantages:
                return ProofResult(
                    status="failed", backend=self.name, error="advantages commitment mismatch"
                )

        claimed_gate = job.commitments.get("gate_decision", "")
        if claimed_gate:
            gate = witness.get("gate_decision", {})
            checks_doc = [
                {
                    "name": c.get("name", ""),
                    "passed": c.get("passed", False),
                    "detail_sha256": sha256_hex(c.get("detail", "").encode()),
                }
                for c in gate.get("checks", [])
            ]
            recomputed_gate = commit(
                {"promotable": gate.get("promotable", False), "checks": checks_doc}
            )
            if recomputed_gate != claimed_gate:
                return ProofResult(
                    status="failed", backend=self.name, error="gate_decision commitment mismatch"
                )

        cycle_doc = {
            "input_batch": input_batch,
            "kept": job.commitments.get("kept", ""),
            "dropped_stale": job.commitments.get("dropped_stale", ""),
            "dropped_hacking": job.commitments.get("dropped_hacking", ""),
            "advantages": claimed_advantages,
            "gate_decision": claimed_gate,
            "reward_spec_hash": job.spec_hashes.get("reward", ""),
            "grpo_spec_hash": job.spec_hashes.get("grpo", ""),
            "gate_spec_hash": job.spec_hashes.get("gate", ""),
            "policy_step": policy_step,
            "max_staleness": max_staleness,
            "accepted": witness.get("accepted", False),
            "reason": witness.get("reason", ""),
        }
        if commit(cycle_doc) != job.commitments.get("cycle", ""):
            return ProofResult(
                status="failed", backend=self.name, error="cycle commitment mismatch"
            )

        return ProofResult(status="attested", backend=self.name)

    def _verify_eval_gate(self, job: ProofJob, witness: dict) -> ProofResult:
        # Phase 3: prove GateDecision.promotable is correct,
        # not merely that the reported run wasn't edited afterwards. The witness
        # carries raw float items bound to the fixed-point commitments; the gate
        # (Wilson CI + seeded paired bootstrap) is re-executed on them and the
        # resulting decision must match the committed one check-for-check.
        from kairo_ml.evals.gate import evaluate_gate
        from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec

        items = witness.get("items", [])
        recomputed = [commit(item) for item in items]
        eval_commitment = commit_sequence(recomputed) if recomputed else ""
        if eval_commitment != job.commitments.get("eval_run", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"eval_run commitment mismatch: recomputed {eval_commitment}",
            )

        baseline_items = witness.get("baseline_items", [])
        claimed_baseline = job.commitments.get("baseline_run", "")
        if claimed_baseline:
            baseline_commits = [commit(item) for item in baseline_items]
            baseline_commitment = commit_sequence(baseline_commits) if baseline_commits else ""
            if baseline_commitment != claimed_baseline:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error="baseline_run commitment mismatch",
                )

        spec_doc = witness.get("gate_spec")
        items_float = witness.get("items_float", [])
        if spec_doc is None or not items_float:
            # Witness predates gate re-execution (or was stripped): the
            # commitments hold but the decision itself was not re-derived.
            return ProofResult(
                status="failed",
                backend=self.name,
                error="witness lacks gate_spec/items_float; cannot re-execute gate",
            )

        # Bind the re-execution inputs to the committed fixed-point items.
        def _bind(float_items: list[dict], committed: list[dict], label: str) -> str | None:
            if len(float_items) != len(committed):
                return f"{label} item count mismatch"
            for f, c in zip(float_items, committed):
                bound = {
                    "item_id": f["item_id"],
                    "passed": f["passed"],
                    "score": to_fixed(f["score"]),
                    "latency_ms": f["latency_ms"],
                    "cost_usd": to_fixed(f["cost_usd"]),
                    "safety_flag": f["safety_flag"],
                }
                if bound != c:
                    return f"{label} item {f['item_id']} diverges from its commitment"
            return None

        if err := _bind(items_float, items, "eval_run"):
            return ProofResult(status="failed", backend=self.name, error=err)
        baseline_items_float = witness.get("baseline_items_float", [])
        if claimed_baseline:
            if err := _bind(baseline_items_float, baseline_items, "baseline_run"):
                return ProofResult(status="failed", backend=self.name, error=err)

        # Bind the declared spec to the committed spec hash, then re-execute.
        spec = PromotionGateSpec(**spec_doc)
        if gate_spec_hash(spec) != job.spec_hashes.get("gate", ""):
            return ProofResult(status="failed", backend=self.name, error="gate_spec_hash mismatch")

        run = EvalRun(
            eval_run_id=witness.get("eval_run_id", ""),
            suite=witness.get("suite", ""),
            model=witness.get("model", ""),
            model_version=witness.get("model_version", ""),
            items=[ItemResult(**f) for f in items_float],
        )
        baseline_run = None
        if claimed_baseline and baseline_items_float:
            baseline_run = EvalRun(
                eval_run_id="baseline",
                suite=witness.get("suite", ""),
                model=witness.get("model", ""),
                model_version="baseline",
                items=[ItemResult(**f) for f in baseline_items_float],
            )
        decision = evaluate_gate(run, spec, baseline=baseline_run)

        claimed = witness.get("gate_decision", {})
        if decision.promotable != claimed.get("promotable"):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"gate re-execution disagrees: promotable={decision.promotable} "
                f"but witness claims {claimed.get('promotable')}",
            )
        recomputed_checks = {c.name: c.passed for c in decision.checks}
        for c in claimed.get("checks", []):
            if recomputed_checks.get(c.get("name")) != c.get("passed"):
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"gate check '{c.get('name')}' re-execution diverged",
                )

        # Finally, the committed decision hash must match what was reported.
        checks_doc = [
            {"name": c.name, "passed": c.passed, "detail_sha256": sha256_hex(c.detail.encode())}
            for c in decision.checks
        ]
        recomputed_gate = commit({"promotable": decision.promotable, "checks": checks_doc})
        if recomputed_gate != job.commitments.get("gate_decision", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error="gate_decision commitment mismatch after re-execution",
            )

        return ProofResult(status="attested", backend=self.name)

    def _verify_rag_evidence(self, job: ProofJob, witness: dict) -> ProofResult:
        """Verify RAG evidence proof (Phase 4)

        Re-verifies:
        - Document hash commitments match witness data
        - Relevance scores are in valid range [0.0, 1.0]
        - Evidence chain commitment matches
        - Spec hash matches current rag_evidence spec
        """
        if job.spec_hashes.get("rag_evidence") != rag_evidence_spec_hash():
            return ProofResult(
                status="failed",
                backend=self.name,
                error="rag_evidence_spec_hash mismatch",
            )

        docs = witness.get("docs", [])
        query_hash = witness.get("query_hash", "")
        query_embedding_hash = witness.get("query_embedding_hash", "")
        corpus_snapshot_hash = witness.get("corpus_snapshot_hash", "")
        grounding_passed = witness.get("grounding_passed", False)
        grounding_threshold_fp = witness.get("grounding_threshold_fp", 0)

        doc_commitments: list[str] = []
        for doc in docs:
            score = doc.get("relevance_score", 0.0)
            score_fp = doc.get("relevance_score_fp", 0)

            if not 0.0 <= score <= 1.0:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"relevance score {score} out of range [0.0, 1.0] "
                    f"for doc {doc.get('doc_id', '')}",
                )

            expected_fp = to_fixed(score)
            if expected_fp != score_fp:
                return ProofResult(
                    status="failed",
                    backend=self.name,
                    error=f"relevance_score_fp mismatch for doc {doc.get('doc_id', '')}: "
                    f"recomputed {expected_fp} != witness {score_fp}",
                )

            doc_item = {
                "doc_id": doc.get("doc_id", ""),
                "doc_hash": doc.get("doc_hash", ""),
                "relevance_score_fp": score_fp,
            }
            h = commit(doc_item)
            doc_commitments.append(h)

        docs_commitment = commit_sequence(doc_commitments) if doc_commitments else ""
        if docs_commitment != job.commitments.get("docs", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"docs commitment mismatch: recomputed {docs_commitment}",
            )

        evidence_chain = {
            "query_hash": query_hash,
            "query_embedding_hash": query_embedding_hash,
            "docs_commitment": docs_commitment,
            "corpus_snapshot_hash": corpus_snapshot_hash,
            "grounding_passed": grounding_passed,
            "grounding_threshold_fp": grounding_threshold_fp,
            "doc_count": len(docs),
        }
        evidence_commitment = commit(evidence_chain)
        if evidence_commitment != job.commitments.get("evidence", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"evidence commitment mismatch: recomputed {evidence_commitment}",
            )

        return ProofResult(status="attested", backend=self.name)

    def _verify_lora_drift(self, job: ProofJob, witness: dict) -> ProofResult:
        """Verify LoRA drift certificate (Phase 5)

        Re-verifies:
        - Drift metrics commitments match witness data
        - Metrics are within declared bounds
        - Certificate commitment matches
        - Spec hash matches bounds
        """
        bounds_data = witness.get("bounds", {})
        bounds = LoraDriftBounds(**bounds_data)

        if job.spec_hashes.get("lora_drift") != lora_drift_spec_hash(bounds):
            return ProofResult(
                status="failed",
                backend=self.name,
                error="lora_drift_spec_hash mismatch",
            )

        metrics_data = witness.get("metrics", {})
        l2_norm = metrics_data.get("l2_norm", 0.0)
        max_delta = metrics_data.get("max_delta", 0.0)
        rank = metrics_data.get("rank", 0)
        modified_modules = metrics_data.get("modified_modules", [])
        num_params = metrics_data.get("num_params", 0)

        l2_norm_fp = metrics_data.get("l2_norm_fp", 0)
        max_delta_fp = metrics_data.get("max_delta_fp", 0)

        if to_fixed(l2_norm) != l2_norm_fp:
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"l2_norm_fp mismatch: recomputed {to_fixed(l2_norm)} != witness {l2_norm_fp}",
            )
        if to_fixed(max_delta) != max_delta_fp:
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"max_delta_fp mismatch: recomputed {to_fixed(max_delta)} != witness {max_delta_fp}",
            )

        metrics_doc = {
            "l2_norm_fp": l2_norm_fp,
            "max_delta_fp": max_delta_fp,
            "rank": rank,
            "modified_modules": sorted(modified_modules),
            "num_params": num_params,
        }
        metrics_commitment = commit(metrics_doc)
        if metrics_commitment != job.commitments.get("metrics", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"metrics commitment mismatch: recomputed {metrics_commitment}",
            )

        metrics_obj = LoraDriftMetrics(
            l2_norm=l2_norm,
            max_delta=max_delta,
            rank=rank,
            modified_modules=modified_modules,
            num_params=num_params,
        )
        within_bounds = metrics_obj.within_bounds(bounds)
        claimed_within_bounds = witness.get("within_bounds", False)
        if within_bounds != claimed_within_bounds:
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"within_bounds mismatch: recomputed {within_bounds} != witness {claimed_within_bounds}",
            )

        adapter_path = witness.get("adapter_path", "")
        base_model_hash = witness.get("base_model_hash", "")
        adapter_hash = witness.get("adapter_hash", "")
        spec_hash = job.spec_hashes.get("lora_drift", "")

        certificate_doc = {
            "adapter_path_sha256": sha256_hex(adapter_path.encode()),
            "base_model_hash": base_model_hash,
            "adapter_hash": adapter_hash,
            "metrics": metrics_commitment,
            "spec_hash": spec_hash,
            "within_bounds": within_bounds,
        }
        certificate_commitment = commit(certificate_doc)
        if certificate_commitment != job.commitments.get("certificate", ""):
            return ProofResult(
                status="failed",
                backend=self.name,
                error=f"certificate commitment mismatch: recomputed {certificate_commitment}",
            )

        return ProofResult(status="attested", backend=self.name)
