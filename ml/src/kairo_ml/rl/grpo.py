"""GRPO group-relative advantages

Group Relative Policy Optimization drops the learned value critic: instead of a
baseline network, it samples a *group* of completions for the same prompt and
uses the group's own reward statistics as the baseline. Each completion's
advantage is its reward standardized within its group:

    A_i = (r_i - mean(group)) / std(group)

so completions above the group average get positive advantage (reinforced) and
those below get negative (suppressed), with the scale normalized per group. This
is pure arithmetic over the scored rewards — no torch — which is why it lives
here and is unit-tested independently of the gradient step

Degenerate groups (size < 2, or all rewards equal) carry no relative signal, so
every advantage is 0.0 rather than a divide-by-zero or an arbitrary sign
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def group_normalize(rewards: Sequence[float]) -> list[float]:
    """Standardize rewards within a single group (the GRPO baseline)"""
    n = len(rewards)
    if n < 2:
        return [0.0] * n
    mean = sum(rewards) / n
    # Population std: the group is the sample space for this prompt, not an estimate of a larger one
    var = sum((r - mean) ** 2 for r in rewards) / n
    std = math.sqrt(var)
    if std == 0.0:
        return [0.0] * n
    return [(r - mean) / std for r in rewards]


def advantages_by_group(groups: Mapping[str, Sequence[float]]) -> dict[str, list[float]]:
    """Group-normalize each group's rewards independently"""
    return {key: group_normalize(rewards) for key, rewards in groups.items()}
