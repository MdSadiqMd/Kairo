from __future__ import annotations

import json

from kairo_ml.rl.aggregate_rewards import aggregate, score_event
from kairo_ml.rl.rewards import (
    R_ACCEPT,
    R_REJECT,
    InteractionSignals,
    compute_reward,
    outcome_from_feedback,
)


def test_accept_and_reject_rewards() -> None:
    assert compute_reward(InteractionSignals(outcome="accepted")).reward == R_ACCEPT
    assert compute_reward(InteractionSignals(outcome="rejected")).reward == R_REJECT
    assert compute_reward(InteractionSignals(outcome="not_shown")).reward == 0.0


def test_edit_persistence_bonus_only_on_positive() -> None:
    with_bonus = compute_reward(InteractionSignals(outcome="accepted", edit_persisted=True))
    assert with_bonus.reward > R_ACCEPT
    # No bonus stacked onto a rejection.
    no_bonus = compute_reward(InteractionSignals(outcome="rejected", edit_persisted=True))
    assert no_bonus.reward == R_REJECT


def test_followup_dissatisfaction_penalizes() -> None:
    r = compute_reward(InteractionSignals(outcome="accepted", followup_dissatisfaction=True))
    assert r.reward < R_ACCEPT


def test_broken_tool_call_cannot_be_positively_rewarded() -> None:
    r = compute_reward(InteractionSignals(outcome="accepted", emitted_broken_tool_call=True))
    assert r.reward <= 0
    assert "broken_tool_call" in r.hacking_flags


def test_clarifying_question_deflection_flagged() -> None:
    r = compute_reward(
        InteractionSignals(outcome="not_shown", deferred_via_clarifying_question=True)
    )
    assert "clarifying_question_deflection" in r.hacking_flags


def test_outcome_from_feedback_is_conservative() -> None:
    assert outcome_from_feedback("accepted", "stop") == "accepted"
    assert outcome_from_feedback("rejected", "stop") == "rejected"
    assert outcome_from_feedback(None, "stop") == "shown_no_action"
    assert outcome_from_feedback(None, "content_filter") == "rejected"


def test_aggregate_scores_and_counts_flags() -> None:
    events = [
        json.dumps(
            {
                "request_id": "1",
                "user_feedback": "accepted",
                "model_version": "v",
                "training_consent": True,
                "prompt_raw": "hello",
                "output_raw": "world",
            }
        ),
        json.dumps(
            {
                "request_id": "2",
                "user_feedback": "rejected",
                "training_consent": True,
                "prompt_raw": "foo",
                "output_raw": "bar",
            }
        ),
        json.dumps(
            {
                "request_id": "3",
                "user_feedback": "accepted",
                "emitted_broken_tool_call": True,
                "training_consent": True,
                "prompt_raw": "a",
                "output_raw": "b",
            }
        ),
        "not json",
    ]
    candidates, stats = aggregate(events)
    assert stats["total"] == 3  # malformed line skipped
    assert stats["flagged"] == 1
    assert len(candidates) == 3
    assert (
        score_event(
            {
                "request_id": "x",
                "user_feedback": "accepted",
                "training_consent": True,
                "prompt_raw": "p",
                "output_raw": "o",
            }
        )["reward"]
        == R_ACCEPT
    )
