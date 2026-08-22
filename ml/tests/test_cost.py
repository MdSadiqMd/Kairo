from __future__ import annotations

import math

from kairo_ml.cost import (
    daily_cost,
    price_route,
    roofline_dollars_per_1m_tokens,
    unit_economics,
)
from kairo_ml.cost.model import dollars_per_1m_tokens
from kairo_ml.cost.tracker import CostTracker


def test_daily_cost_two_regimes() -> None:
    # Below capacity: ~fixed fleet regardless of volume.
    assert math.isclose(daily_cost(100_000, "B"), 230.01, abs_tol=0.05)
    assert math.isclose(daily_cost(5_000_000, "B"), 230.5, abs_tol=0.1)
    # Above one cascade's capacity (80M/day) a second replica-set kicks in.
    assert daily_cost(100_000_000, "B") > daily_cost(80_000_000, "B") + 100
    assert math.isclose(daily_cost(100_000, "A"), 70.01, abs_tol=0.05)


def test_dollars_per_1m_amortization_curve_drops_with_volume() -> None:
    assert dollars_per_1m_tokens(100_000, "B") > dollars_per_1m_tokens(5_000_000, "B")
    assert dollars_per_1m_tokens(0, "B") == float("inf")


def test_unit_economics_shape() -> None:
    ue = unit_economics(5_000_000, "B")
    assert ue.replica_sets == 1
    assert ue.daily_cost_usd > 0
    assert unit_economics(100_000_000, "B").replica_sets == 2


def test_roofline_floor_matches_plan_example() -> None:
    # Worked example: Model-32B BF16 = 64GB on 4x A10G (600 GB/s each).
    # Floor ≈ 27 ms/token → ~37 tok/s. At $5.672/hr for the g5.12xlarge node.
    per_1m = roofline_dollars_per_1m_tokens(
        weight_bytes=64e9, gpus=4, gpu="a10g", gpu_hourly_usd=5.672 / 4
    )
    # ~37 tok/s single-stream → the physics floor is a small $/1M number.
    assert 0.01 < per_1m < 100


def test_price_route_and_tracker() -> None:
    fast = price_route(
        route="fast", gpu_hourly_usd=1.006, input_tokens_per_s=5000, output_tokens_per_s=2000
    )
    reasoner = price_route(
        route="reasoning", gpu_hourly_usd=5.672, input_tokens_per_s=3000, output_tokens_per_s=40
    )
    # The reasoner's output tokens are far pricier (decode-bound).
    assert reasoner.output_per_1m > fast.output_per_1m * 10

    tracker = CostTracker({"fast": fast, "reasoning": reasoner})
    tracker.record(route="fast", input_tokens=1000, output_tokens=500)
    tracker.record(route="reasoning", input_tokens=1000, output_tokens=500)
    report = tracker.report()
    assert report.total_requests == 2
    assert report.per_route["reasoning"]["cost_usd"] > report.per_route["fast"]["cost_usd"]
    assert report.blended_cost_per_request > 0
