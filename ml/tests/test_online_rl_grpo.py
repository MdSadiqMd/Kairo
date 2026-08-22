from __future__ import annotations

import math

from kairo_ml.rl.grpo import advantages_by_group, group_normalize


def test_group_normalize_is_zero_mean_unit_std() -> None:
    adv = group_normalize([1.0, 2.0, 3.0])
    assert math.isclose(sum(adv), 0.0, abs_tol=1e-9)
    # Population std normalization: values are ±1.2247, 0.
    assert math.isclose(adv[0], -1.224744871391589, rel_tol=1e-9)
    assert math.isclose(adv[2], 1.224744871391589, rel_tol=1e-9)
    # Standardized to unit population variance.
    var = sum(a * a for a in adv) / len(adv)
    assert math.isclose(var, 1.0, rel_tol=1e-9)


def test_group_normalize_ranks_preserved() -> None:
    adv = group_normalize([0.75, -0.25, -0.25, 0.75])
    # Higher rewards get positive advantage, lower get negative.
    assert adv[0] > 0 and adv[3] > 0
    assert adv[1] < 0 and adv[2] < 0


def test_degenerate_group_all_equal_gives_zero() -> None:
    assert group_normalize([0.5, 0.5, 0.5]) == [0.0, 0.0, 0.0]


def test_single_sample_group_gives_zero() -> None:
    assert group_normalize([0.9]) == [0.0]


def test_empty_group() -> None:
    assert group_normalize([]) == []


def test_advantages_by_group_independent() -> None:
    result = advantages_by_group({"a": [1.0, 3.0], "b": [5.0, 5.0]})
    assert result["a"][0] < 0 < result["a"][1]
    assert result["b"] == [0.0, 0.0]  # degenerate group unaffected by group a
