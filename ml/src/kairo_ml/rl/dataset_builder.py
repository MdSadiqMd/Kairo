"""Dataset builders for online RL training

Converts scored rollouts into training-compatible formats for different
RL algorithms (RLOO, Online DPO)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kairo_ml.rl.online_loop import Rollout


@dataclass
class RLSample:
    """A single RL training sample with prompt, completion, and advantage"""

    prompt: str
    completion: str
    advantage: float
    reward: float
    group_id: str


@dataclass
class PreferencePair:
    """A preference pair for DPO-style training"""

    prompt: str
    chosen: str
    rejected: str
    chosen_reward: float
    rejected_reward: float


def build_rl_dataset(
    rollouts: Sequence[Rollout],
    advantages: Sequence[float],
) -> list[RLSample]:
    """Convert rollouts with advantages to RL samples

    Reads prompt_raw and output_raw directly from Rollout dataclass fields
    """
    if len(rollouts) != len(advantages):
        raise ValueError(
            f"Length mismatch: {len(rollouts)} rollouts vs {len(advantages)} advantages"
        )

    samples = []
    for rollout, adv in zip(rollouts, advantages, strict=True):
        prompt = rollout.prompt_raw
        completion = rollout.output_raw

        samples.append(
            RLSample(
                prompt=prompt,
                completion=completion,
                advantage=adv,
                reward=rollout.reward,
                group_id=rollout.group_id,
            )
        )
    return samples


def build_preference_pairs(
    rollouts: Sequence[Rollout],
) -> list[PreferencePair]:
    """Convert grouped rollouts to preference pairs for Online DPO

    Groups rollouts by group_id, then creates pairs where the higher-reward
    completion is chosen and the lower-reward is rejected
    Reads prompt_raw and output_raw directly from Rollout dataclass fields
    """
    groups: dict[str, list[Rollout]] = {}
    for r in rollouts:
        groups.setdefault(r.group_id, []).append(r)

    pairs = []
    for group_id, group_rollouts in groups.items():
        if len(group_rollouts) < 2:
            continue

        sorted_rollouts = sorted(group_rollouts, key=lambda r: r.reward, reverse=True)

        for i, chosen in enumerate(sorted_rollouts[:-1]):
            for rejected in sorted_rollouts[i + 1 :]:
                if chosen.reward == rejected.reward:
                    continue

                prompt = chosen.prompt_raw
                if not prompt:
                    prompt = rejected.prompt_raw

                chosen_completion = chosen.output_raw
                rejected_completion = rejected.output_raw

                if prompt and chosen_completion and rejected_completion:
                    pairs.append(
                        PreferencePair(
                            prompt=prompt,
                            chosen=chosen_completion,
                            rejected=rejected_completion,
                            chosen_reward=chosen.reward,
                            rejected_reward=rejected.reward,
                        )
                    )

    return pairs


def to_trl_rloo_format(samples: Sequence[RLSample]) -> list[dict]:
    """Convert RL samples to TRL's RLOO trainer format"""
    return [
        {
            "query": s.prompt,
            "response": s.completion,
            "advantage": s.advantage,
        }
        for s in samples
        if s.prompt and s.completion
    ]


def to_trl_dpo_format(pairs: Sequence[PreferencePair]) -> list[dict]:
    """Convert preference pairs to TRL's DPO trainer format"""
    return [
        {
            "prompt": p.prompt,
            "chosen": p.chosen,
            "rejected": p.rejected,
        }
        for p in pairs
    ]
