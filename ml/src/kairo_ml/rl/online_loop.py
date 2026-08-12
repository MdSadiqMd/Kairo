"""Real-time (online) RL loop

One cycle of Cursor-style online RL:

1. Collect scored rollouts (from `kairo_ml.rl.rewards` via the reward
   aggregator) for the current policy
2. Filter them: drop reward-hacking suspects, and reject samples that are too
   off-policy (the staleness guard)
3. Advantage: group-normalize the kept rewards into GRPO advantages
   (`kairo_ml.rl.grpo`) — pure math, tested
4. Update: run exactly one on-policy gradient step (the injected
   `PolicyUpdater`; the real one lazily imports trl/torch)
5. Gate: run the per-cycle eval gate (`kairo_ml.evals.gate.evaluate_gate`)
   on the resulting candidate and discard it if it regresses. A
   candidate that fails the gate is never deployed — the loop is a *fast gated
   loop*, not ungated online weight updates

Everything except the gradient step is pure python and unit-tested with fakes

Two guardrails are structural, not optional:

- Staleness. Policy-gradient updates are only valid on actions sampled from
  the policy being optimized. A sample generated more than `max_staleness`
  policy steps ago is too off-policy — using it "increases the chance of
  over-optimizing behaviors past the point where they stop improving the
  objective" — so it is rejected
- Reward hacking. Any candidate whose reward carries `hacking_flags` (a
  broken tool call, a clarifying-question deflection) is dropped before it can
  reinforce the gamed behavior
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from kairo_common import get_logger

from kairo_ml.evals.gate import GateDecision, evaluate_gate
from kairo_ml.evals.models import EvalRun, PromotionGateSpec
from kairo_ml.rl.grpo import advantages_by_group

log = get_logger("online-rl-loop")


@dataclass(frozen=True)
class Rollout:
    group_id: str  # completions sharing a group_id are the same prompt's samples
    reward: float
    policy_step: int  # the policy version that generated this sample
    hacking_flags: tuple[str, ...] = ()
    request_id: str = ""
    # Text payloads for the training step — prompt_raw is JSON-serialized
    # messages, output_raw is the assistant's response.
    prompt_raw: str = ""
    output_raw: str = ""


def rollouts_from_scored(
    candidates: Sequence[Mapping[str, Any]],
    *,
    default_group: str = "default",
    default_policy_step: int = 0,
) -> list[Rollout]:
    """Adapt reward-aggregator output (``score_event`` dicts) into rollouts."""
    rollouts: list[Rollout] = []
    for c in candidates:
        rollouts.append(
            Rollout(
                group_id=str(c.get("group_id", default_group)),
                reward=float(c["reward"]),
                policy_step=int(c.get("policy_step", default_policy_step)),
                hacking_flags=tuple(c.get("hacking_flags", ()) or ()),
                request_id=str(c.get("request_id", "")),
                prompt_raw=str(c.get("prompt_raw", "")),
                output_raw=str(c.get("output_raw", "")),
            )
        )
    return rollouts


class PolicyUpdater(Protocol):
    """Performs one on-policy gradient step given per-sample advantages"""

    def apply_update(self, advantages: Sequence[float], rollouts: Sequence[Rollout]) -> None: ...


Evaluator = Callable[[], EvalRun]


@dataclass(frozen=True)
class CycleResult:
    accepted: bool
    reason: str
    decision: GateDecision | None = None
    advantages: list[float] = field(default_factory=list)
    kept: list[Rollout] = field(default_factory=list)
    dropped_stale: list[Rollout] = field(default_factory=list)
    dropped_hacking: list[Rollout] = field(default_factory=list)


class OnlineRLLoop:
    def __init__(
        self,
        *,
        spec: PromotionGateSpec,
        updater: PolicyUpdater,
        evaluator: Evaluator,
        max_staleness: int = 1,
        policy_step: int = 0,
    ) -> None:
        self.spec = spec
        self.updater = updater
        self.evaluator = evaluator
        self.max_staleness = max_staleness
        self.policy_step = policy_step

    def filter_rollouts(
        self, rollouts: Sequence[Rollout]
    ) -> tuple[list[Rollout], list[Rollout], list[Rollout]]:
        """Split rollouts into (kept, dropped_stale, dropped_hacking)"""
        kept: list[Rollout] = []
        stale: list[Rollout] = []
        hacking: list[Rollout] = []
        for r in rollouts:
            # Reward-hacking discard takes priority: a gamed sample must never
            # reinforce the behavior, regardless of freshness.
            if r.hacking_flags:
                hacking.append(r)
            elif self.policy_step - r.policy_step > self.max_staleness:
                stale.append(r)
            else:
                kept.append(r)
        return kept, stale, hacking

    def compute_advantages(self, kept: Sequence[Rollout]) -> list[float]:
        """GRPO advantages aligned to `kept` order

        Falls back to raw rewards when groups are all singletons (local testing
        without repeated prompts). This lets the updater train on positive-reward
        samples even without the group-relative baseline
        """
        groups: dict[str, list[float]] = {}
        for r in kept:
            groups.setdefault(r.group_id, []).append(r.reward)

        all_singleton = all(len(g) == 1 for g in groups.values())
        if all_singleton:
            log.info("GRPO fallback: all groups singleton, using raw rewards as advantages")
            return [r.reward for r in kept]

        by_group = advantages_by_group(groups)
        cursor: dict[str, int] = {}
        advantages: list[float] = []
        for r in kept:
            i = cursor.get(r.group_id, 0)
            advantages.append(by_group[r.group_id][i])
            cursor[r.group_id] = i + 1
        return advantages

    def run_cycle(
        self, rollouts: Sequence[Rollout], *, baseline: EvalRun | None = None
    ) -> CycleResult:
        kept, stale, hacking = self.filter_rollouts(rollouts)
        if stale:
            log.info("rejected stale rollouts", extra={"count": len(stale)})
        if hacking:
            log.warning("dropped reward-hacking rollouts", extra={"count": len(hacking)})

        if not kept:
            # No valid on-policy signal this cycle: do not update or deploy.
            return CycleResult(
                accepted=False,
                reason="no_onpolicy_samples",
                dropped_stale=stale,
                dropped_hacking=hacking,
            )

        advantages = self.compute_advantages(kept)
        self.updater.apply_update(advantages, kept)

        candidate = self.evaluator()
        decision = evaluate_gate(candidate, self.spec, baseline=baseline)
        if not decision.promotable:
            # Regressing candidate is discarded; the current checkpoint stays.
            log.warning("candidate discarded by eval gate")
            return CycleResult(
                accepted=False,
                reason="eval_gate_regression",
                decision=decision,
                advantages=advantages,
                kept=kept,
                dropped_stale=stale,
                dropped_hacking=hacking,
            )

        self.policy_step += 1
        log.info("candidate accepted", extra={"policy_step": self.policy_step})
        return CycleResult(
            accepted=True,
            reason="promoted",
            decision=decision,
            advantages=advantages,
            kept=kept,
            dropped_stale=stale,
            dropped_hacking=hacking,
        )
