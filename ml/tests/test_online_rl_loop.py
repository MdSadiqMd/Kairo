from __future__ import annotations

from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec
from kairo_ml.rl.online_loop import (
    OnlineRLLoop,
    Rollout,
    rollouts_from_scored,
)


class FakeUpdater:
    def __init__(self) -> None:
        self.calls: list[tuple[list[float], list[Rollout]]] = []

    def apply_update(self, advantages: object, rollouts: object) -> None:
        assert isinstance(advantages, list) or hasattr(advantages, "__iter__")
        self.calls.append((list(advantages), list(rollouts)))  # type: ignore[arg-type]


def _run(passes: int, n: int) -> EvalRun:
    items = [
        ItemResult(item_id=str(i), passed=i < passes, latency_ms=10, cost_usd=0.001)
        for i in range(n)
    ]
    return EvalRun(eval_run_id="r", suite="smoke", model="cand", model_version="v2", items=items)


def _health_check_spec() -> PromotionGateSpec:
    # A fast per-cycle gate: floor on pass rate, sized on min_n only.
    return PromotionGateSpec(
        min_pass_rate=0.5, min_detectable_effect=0.0, min_n=10, max_safety_regression=0.01
    )


def _loop(
    updater: FakeUpdater, run: EvalRun, *, max_staleness: int = 1, step: int = 0
) -> OnlineRLLoop:
    return OnlineRLLoop(
        spec=_health_check_spec(),
        updater=updater,
        evaluator=lambda: run,
        max_staleness=max_staleness,
        policy_step=step,
    )


def _fresh(reward: float, group: str, step: int, **kw: object) -> Rollout:
    return Rollout(group_id=group, reward=reward, policy_step=step, **kw)  # type: ignore[arg-type]


def test_accepts_passing_candidate_and_advances_step() -> None:
    updater = FakeUpdater()
    loop = _loop(updater, _run(passes=20, n=20), step=5)
    rollouts = [
        _fresh(0.75, "g1", 5),
        _fresh(-0.25, "g1", 5),
        _fresh(0.75, "g2", 5),
        _fresh(-0.25, "g2", 5),
    ]
    result = loop.run_cycle(rollouts)
    assert result.accepted is True
    assert result.reason == "promoted"
    assert loop.policy_step == 6  # advanced only on accept
    assert len(updater.calls) == 1
    assert len(result.advantages) == 4  # one on-policy update over all kept


def test_discards_regressing_candidate() -> None:
    updater = FakeUpdater()
    loop = _loop(updater, _run(passes=2, n=20), step=5)  # 10% pass rate < 0.5 floor
    rollouts = [_fresh(0.75, "g1", 5), _fresh(-0.25, "g1", 5)]
    result = loop.run_cycle(rollouts)
    assert result.accepted is False
    assert result.reason == "eval_gate_regression"
    assert result.decision is not None and result.decision.promotable is False
    # The update step ran, but the candidate is not deployed and the step holds.
    assert len(updater.calls) == 1
    assert loop.policy_step == 5


def test_drops_reward_hacking_candidate() -> None:
    updater = FakeUpdater()
    loop = _loop(updater, _run(passes=20, n=20), step=5)
    rollouts = [
        _fresh(0.75, "g1", 5),
        _fresh(-0.25, "g1", 5),
        Rollout(group_id="g1", reward=0.75, policy_step=5, hacking_flags=("broken_tool_call",)),
    ]
    result = loop.run_cycle(rollouts)
    assert len(result.dropped_hacking) == 1
    assert result.dropped_hacking[0].hacking_flags == ("broken_tool_call",)
    assert len(result.kept) == 2  # hacking sample excluded from the update
    assert len(updater.calls[0][0]) == 2


def test_rejects_stale_samples() -> None:
    updater = FakeUpdater()
    loop = _loop(updater, _run(passes=20, n=20), max_staleness=1, step=5)
    rollouts = [
        _fresh(0.75, "g1", 5),  # fresh
        _fresh(-0.25, "g1", 4),  # 1 step old: within tolerance
        _fresh(0.75, "g1", 2),  # 3 steps old: too off-policy
    ]
    result = loop.run_cycle(rollouts)
    assert len(result.dropped_stale) == 1
    assert result.dropped_stale[0].policy_step == 2
    assert len(result.kept) == 2


def test_no_kept_samples_skips_update_entirely() -> None:
    updater = FakeUpdater()
    loop = _loop(updater, _run(passes=20, n=20), max_staleness=1, step=10)
    rollouts = [
        _fresh(0.75, "g1", 2),  # stale
        Rollout(group_id="g1", reward=0.75, policy_step=10, hacking_flags=("broken_tool_call",)),
    ]
    result = loop.run_cycle(rollouts)
    assert result.accepted is False
    assert result.reason == "no_onpolicy_samples"
    assert updater.calls == []  # never updated on an empty on-policy batch
    assert loop.policy_step == 10


def test_rollouts_from_scored_adapter() -> None:
    scored = [
        {
            "request_id": "1",
            "reward": 0.75,
            "hacking_flags": [],
            "group_id": "g1",
            "policy_step": 3,
        },
        {"request_id": "2", "reward": -0.25, "hacking_flags": ["broken_tool_call"]},
    ]
    rollouts = rollouts_from_scored(scored, default_group="d", default_policy_step=7)
    assert rollouts[0].group_id == "g1"
    assert rollouts[0].policy_step == 3
    assert rollouts[1].group_id == "d"  # default applied
    assert rollouts[1].policy_step == 7
    assert rollouts[1].hacking_flags == ("broken_tool_call",)
