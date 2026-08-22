from __future__ import annotations

from kairo_common.proofs import ProofJob
from kairo_ml.proofs import witness as witness_mod
from kairo_ml.proofs.backends import HashCommitBackend
from kairo_ml.proofs.canonical import SCALE, commit, commit_sequence, to_fixed
from kairo_ml.proofs.fixedpoint import group_normalize_fixed
from kairo_ml.proofs.spec_hashes import grpo_spec_hash, reward_spec_hash


class TestCanonical:
    def test_to_fixed_positive(self):
        assert to_fixed(0.75) == 750_000
        assert to_fixed(1.0) == 1_000_000
        assert to_fixed(0.5) == 500_000

    def test_to_fixed_negative(self):
        assert to_fixed(-0.25) == -250_000
        assert to_fixed(-1.0) == -1_000_000

    def test_to_fixed_zero(self):
        assert to_fixed(0.0) == 0

    def test_to_fixed_rounding(self):
        assert to_fixed(0.0000005) == 0
        assert to_fixed(0.0000015) == 2

    def test_commit_deterministic(self):
        obj = {"a": 1, "b": 2}
        h1 = commit(obj)
        h2 = commit(obj)
        assert h1 == h2
        assert len(h1) == 64

    def test_commit_order_independent(self):
        h1 = commit({"a": 1, "b": 2})
        h2 = commit({"b": 2, "a": 1})
        assert h1 == h2

    def test_commit_sequence_deterministic(self):
        items = [commit({"a": 1}), commit({"b": 2})]
        h1 = commit_sequence(items)
        h2 = commit_sequence(items)
        assert h1 == h2

    def test_commit_sequence_order_matters(self):
        c1 = commit({"a": 1})
        c2 = commit({"b": 2})
        h1 = commit_sequence([c1, c2])
        h2 = commit_sequence([c2, c1])
        assert h1 != h2


class TestFixedPoint:
    def test_group_normalize_fixed_basic(self):
        rewards = [750_000, -250_000, 0]
        advantages = group_normalize_fixed(rewards)
        assert len(advantages) == 3
        assert sum(advantages) // 3 < 10000

    def test_group_normalize_fixed_all_same(self):
        rewards = [500_000, 500_000, 500_000]
        advantages = group_normalize_fixed(rewards)
        assert advantages == [0, 0, 0]

    def test_group_normalize_fixed_empty(self):
        assert group_normalize_fixed([]) == []

    def test_group_normalize_fixed_single(self):
        assert group_normalize_fixed([1_000_000]) == [0]

    def test_fixed_vs_float_agreement(self):
        from kairo_ml.rl.grpo import group_normalize

        rewards_float = [0.75, -0.25, 0.0, 0.5, -0.1]
        rewards_fp = [to_fixed(r) for r in rewards_float]

        advantages_float = group_normalize(rewards_float)
        advantages_fp = group_normalize_fixed(rewards_fp)

        for af, afp in zip(advantages_float, advantages_fp):
            assert abs(af - afp / SCALE) < 1e-4, f"Float {af} vs FP {afp / SCALE}"


class TestSpecHashes:
    def test_reward_spec_hash_stable(self):
        h1 = reward_spec_hash()
        h2 = reward_spec_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_grpo_spec_hash_stable(self):
        h1 = grpo_spec_hash()
        h2 = grpo_spec_hash()
        assert h1 == h2
        assert len(h1) == 64


class TestHashCommitBackend:
    def test_supports_kinds(self):
        backend = HashCommitBackend()
        assert backend.supports("rl_reward_batch")
        assert backend.supports("rl_cycle")
        assert backend.supports("eval_gate")
        assert not backend.supports("unknown_kind")

    def test_verify_reward_batch_success(self):
        backend = HashCommitBackend()

        items = [
            {
                "request_id": "req1",
                "outcome": "accepted",
                "edit_persisted": False,
                "followup_dissatisfaction": False,
                "emitted_broken_tool_call": False,
                "deferred_via_clarifying_question": False,
                "reward_fp": 750_000,
            },
            {
                "request_id": "req2",
                "outcome": "rejected",
                "edit_persisted": False,
                "followup_dissatisfaction": False,
                "emitted_broken_tool_call": False,
                "deferred_via_clarifying_question": False,
                "reward_fp": -250_000,
            },
        ]

        item_commits = [commit(item) for item in items]
        batch_commitment = commit_sequence(item_commits)

        job = ProofJob(
            proof_id="proof_test",
            kind="rl_reward_batch",
            subject_id="batch_test",
            zk_inference=True,
            commitments={"input_batch": batch_commitment},
            spec_hashes={"reward": reward_spec_hash()},
            witness_uri="file:///tmp/witness.json",
            created_at="2024-01-01T00:00:00Z",
        )

        witness = {"items": items}
        result = backend.prove(job, witness)
        assert result.status == "attested", result.error

    def test_verify_reward_batch_tampered_reward(self):
        backend = HashCommitBackend()

        items = [
            {
                "request_id": "req1",
                "outcome": "accepted",
                "edit_persisted": False,
                "followup_dissatisfaction": False,
                "emitted_broken_tool_call": False,
                "deferred_via_clarifying_question": False,
                "reward_fp": 999_999,
            },
        ]

        item_commits = [commit(item) for item in items]
        batch_commitment = commit_sequence(item_commits)

        job = ProofJob(
            proof_id="proof_test",
            kind="rl_reward_batch",
            subject_id="batch_test",
            zk_inference=True,
            commitments={"input_batch": batch_commitment},
            spec_hashes={"reward": reward_spec_hash()},
            witness_uri="file:///tmp/witness.json",
            created_at="2024-01-01T00:00:00Z",
        )

        witness = {"items": items}
        result = backend.prove(job, witness)
        assert result.status == "failed"
        assert "reward_fp mismatch" in result.error

    @staticmethod
    def _cycle_job_and_witness(tamper=None):
        """Produce a (job, witness) pair through the REAL writer, witness.commit_cycle."""
        from kairo_ml.proofs import witness as witness_mod
        from kairo_ml.rl.online_loop import CycleResult, Rollout

        rollouts = [
            Rollout(group_id="g1", reward=0.75, policy_step=100, request_id="r1"),
            Rollout(group_id="g1", reward=-0.25, policy_step=100, request_id="r2"),
            Rollout(group_id="g1", reward=0.0, policy_step=80, request_id="r3"),
            Rollout(
                group_id="g1",
                reward=0.9,
                policy_step=100,
                hacking_flags=("broken_tool_call",),
                request_id="r4",
            ),
        ]
        kept = [rollouts[0], rollouts[1]]
        result = CycleResult(
            accepted=True,
            reason="gate passed",
            advantages=[1.0, -1.0],
            kept=kept,
            dropped_stale=[rollouts[2]],
            dropped_hacking=[rollouts[3]],
        )

        captured = {}

        class CaptureSink:
            def send(self, job, witness):
                captured["job"] = job
                captured["witness"] = witness

        from kairo_ml.evals.models import PromotionGateSpec

        witness_mod.commit_cycle(
            rollouts,
            result,
            policy_step=100,
            max_staleness=1,
            spec=PromotionGateSpec(min_pass_rate=0.5, min_n=10),
            sink=CaptureSink(),
        )
        job, wit = captured["job"], captured["witness"]
        if tamper:
            tamper(wit)
        return job, wit

    def test_verify_cycle_end_to_end(self):
        backend = HashCommitBackend()
        job, wit = self._cycle_job_and_witness()
        result = backend.prove(job, wit)
        assert result.status == "attested", result.error

    def test_verify_cycle_tampered_rollout_reward(self):
        backend = HashCommitBackend()

        def tamper(wit):
            wit["rollouts"][0]["reward_fp"] = 999_999

        job, wit = self._cycle_job_and_witness(tamper=tamper)
        result = backend.prove(job, wit)
        assert result.status == "failed"
        assert "mismatch" in result.error

    def test_verify_cycle_dropped_hacking_item_reintroduced(self):
        backend = HashCommitBackend()

        def tamper(wit):
            for r in wit["rollouts"]:
                if r["request_id"] == "r4":
                    r["hacking_flags"] = []

        job, wit = self._cycle_job_and_witness(tamper=tamper)
        result = backend.prove(job, wit)
        assert result.status == "failed"
        assert "mismatch" in result.error

    def test_reward_batch_end_to_end_via_score_event(self):
        from kairo_ml.proofs import witness as witness_mod
        from kairo_ml.rl.aggregate_rewards import score_event

        events = [
            {
                "training_consent": True,
                "request_id": "req1",
                "prompt_raw": "write a function",
                "output_raw": "def f(): pass",
                "user_feedback": "accepted",
                "edit_persisted": True,
            },
            {
                "training_consent": True,
                "request_id": "req2",
                "prompt_raw": "fix the bug",
                "output_raw": "done",
                "user_feedback": "rejected",
            },
        ]
        candidates = [score_event(e) for e in events]
        assert all(c is not None for c in candidates)

        captured = {}

        class CaptureSink:
            def send(self, job, witness):
                captured["job"] = job
                captured["witness"] = witness

        witness_mod.commit_reward_batch(candidates, {"total": 2}, run_id="test", sink=CaptureSink())

        backend = HashCommitBackend()
        result = backend.prove(captured["job"], captured["witness"])
        assert result.status == "attested", result.error

    @staticmethod
    def _eval_fixture(pass_count: int = 9, fail_count: int = 1):
        from kairo_ml.evals.gate import evaluate_gate
        from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec

        items = [
            ItemResult(item_id=f"p{i}", passed=True, score=1.0, latency_ms=100 + i, cost_usd=0.001)
            for i in range(pass_count)
        ] + [
            ItemResult(item_id=f"f{i}", passed=False, score=0.0, latency_ms=150 + i, cost_usd=0.001)
            for i in range(fail_count)
        ]
        run = EvalRun(
            eval_run_id="eval_test",
            suite="smoke_v1",
            model="model-32b",
            model_version="cand-1",
            items=items,
        )
        spec = PromotionGateSpec(min_pass_rate=0.5, min_n=5, min_detectable_effect=0.0)
        decision = evaluate_gate(run, spec)
        return run, spec, decision

    def _committed_eval(self, run, spec, decision):
        captured = {}

        class CaptureSink:
            def send(self, job, witness):
                captured["job"] = job
                captured["witness"] = witness

        witness_mod.commit_eval_run(run, decision, spec, sink=CaptureSink())
        return captured["job"], captured["witness"]

    def test_verify_eval_gate_reexecutes_and_attests(self):
        run, spec, decision = self._eval_fixture()
        job, witness = self._committed_eval(run, spec, decision)
        result = HashCommitBackend().prove(job, witness)
        assert result.status == "attested", result.error

    def test_verify_eval_gate_rejects_flipped_promotable(self):
        # A decision flipped after the run (promote despite failing evals) must
        # be caught by gate re-execution, not just by commitment re-hashing.
        run, spec, decision = self._eval_fixture(pass_count=2, fail_count=8)
        assert not decision.promotable
        job, witness = self._committed_eval(run, spec, decision)
        witness["gate_decision"]["promotable"] = True
        result = HashCommitBackend().prove(job, witness)
        assert result.status == "failed"
        assert "promotable" in (result.error or "")

    def test_verify_eval_gate_rejects_tampered_item(self):
        run, spec, decision = self._eval_fixture()
        job, witness = self._committed_eval(run, spec, decision)
        witness["items_float"][0]["passed"] = False  # diverges from commitment
        result = HashCommitBackend().prove(job, witness)
        assert result.status == "failed"

    def test_verify_eval_gate_rejects_witness_without_reexecution_data(self):
        run, spec, decision = self._eval_fixture()
        job, witness = self._committed_eval(run, spec, decision)
        del witness["gate_spec"]
        result = HashCommitBackend().prove(job, witness)
        assert result.status == "failed"
        assert "re-execute" in (result.error or "")

    def test_verify_eval_gate_with_baseline(self):
        from kairo_ml.evals.gate import evaluate_gate
        from kairo_ml.evals.models import EvalRun, ItemResult

        run, spec, _ = self._eval_fixture()
        baseline_items = [
            ItemResult(
                item_id=f"p{i}", passed=(i % 2 == 0), score=1.0, latency_ms=90 + i, cost_usd=0.001
            )
            for i in range(10)
        ]
        baseline = EvalRun(
            eval_run_id="baseline",
            suite="smoke_v1",
            model="model-32b",
            model_version="baseline",
            items=baseline_items,
        )
        decision = evaluate_gate(run, spec, baseline=baseline)

        captured = {}

        class CaptureSink:
            def send(self, job, witness):
                captured["job"] = job
                captured["witness"] = witness

        witness_mod.commit_eval_run(run, decision, spec, baseline=baseline, sink=CaptureSink())
        result = HashCommitBackend().prove(captured["job"], captured["witness"])
        assert result.status == "attested", result.error


class TestToggle:
    def test_zk_disabled_skips_witness(self, monkeypatch):
        monkeypatch.setenv("ZK_INFERENCE", "false")

        from importlib import reload

        import kairo_ml.proofs.settings
        from kairo_ml.proofs.settings import zk_enabled

        reload(kairo_ml.proofs.settings)

        assert not zk_enabled()

    def test_zk_enabled_default_false_for_missing_env(self, monkeypatch):
        monkeypatch.delenv("ZK_INFERENCE", raising=False)

        from importlib import reload

        import kairo_ml.proofs.settings
        from kairo_ml.proofs.settings import zk_enabled

        reload(kairo_ml.proofs.settings)

        assert not zk_enabled()
