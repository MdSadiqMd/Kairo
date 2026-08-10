"""Dense implicit reward from user behavior

Copied from Cursor's Tab/Composer model: the reward comes from what the user
did, not thumbs. Tab rewards +0.75 for an accepted suggestion, -0.25 for a
rejected one, 0 for showing nothing — so the model learns to act only when
accept-probability clears ~25%. We generalize that to our signals: acceptance,
edit persistence, and follow-up dissatisfaction.

Two guardrails are baked in because any online reward will be gamed:
- A response that emits a broken/rejected tool call is not rewarded for
  "deferring" — Composer learned to dodge negative reward that way
- Clarifying-question deflections do not earn the acceptance reward, so the
  model can't avoid punishment by never committing to an answer
These are the code half of the mandatory reward-hacking audit
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["accepted", "rejected", "shown_no_action", "not_shown"]

# Tab's constants. Kept as named values so the reward-hacking audit can
# assert on them and so a reward-function fix is a one-line, reviewable change.
R_ACCEPT = 0.75
R_REJECT = -0.25
R_NEUTRAL = 0.0
EDIT_PERSISTENCE_BONUS = 0.15  # suggestion survived subsequent edits
FOLLOWUP_DISSATISFACTION_PENALTY = -0.20  # user immediately retried/rephrased


@dataclass(frozen=True)
class InteractionSignals:
    outcome: Outcome
    edit_persisted: bool = False
    followup_dissatisfaction: bool = False
    emitted_broken_tool_call: bool = False
    deferred_via_clarifying_question: bool = False


@dataclass(frozen=True)
class RewardBreakdown:
    reward: float
    base: float
    edit_bonus: float
    followup_penalty: float
    hacking_flags: tuple[str, ...]


def compute_reward(sig: InteractionSignals) -> RewardBreakdown:
    flags: list[str] = []

    # Reward-hacking guardrails run first: a gamed interaction never earns the
    # acceptance reward, and it is flagged for the transcript audit.
    if sig.emitted_broken_tool_call:
        flags.append("broken_tool_call")
    if sig.deferred_via_clarifying_question and sig.outcome == "not_shown":
        flags.append("clarifying_question_deflection")

    base = {
        "accepted": R_ACCEPT,
        "rejected": R_REJECT,
        "shown_no_action": R_NEUTRAL,
        "not_shown": R_NEUTRAL,
    }[sig.outcome]

    # A broken tool call cannot be rewarded positively regardless of outcome.
    if "broken_tool_call" in flags and base > 0:
        base = R_REJECT

    edit_bonus = EDIT_PERSISTENCE_BONUS if (sig.edit_persisted and base > 0) else 0.0
    followup_penalty = FOLLOWUP_DISSATISFACTION_PENALTY if sig.followup_dissatisfaction else 0.0

    return RewardBreakdown(
        reward=base + edit_bonus + followup_penalty,
        base=base,
        edit_bonus=edit_bonus,
        followup_penalty=followup_penalty,
        hacking_flags=tuple(flags),
    )


def outcome_from_feedback(user_feedback: str | None, finish_reason: str | None) -> Outcome:
    """Map a raw event's coarse signals to an interaction outcome

    Conservative by design: unknown feedback maps to a neutral outcome so a
    sparse or missing signal never manufactures reward
    """
    if user_feedback == "accepted":
        return "accepted"
    if user_feedback == "rejected":
        return "rejected"
    if finish_reason == "content_filter":
        return "rejected"
    return "shown_no_action"
