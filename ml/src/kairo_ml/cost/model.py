"""Unit-economics model

Turns the plan's napkin math into a live, testable model. The two-regime cost
formula, the roofline $/token floor, and the per-route pricing that anchors
routing thresholds all live here so the router, dashboards, and
cost alerts share one implementation instead of scattered magic numbers.

The dollar constants are AWS On-Demand list (us-east-1) and are
inputs, not truths — recalibrate `C` (tokens/day per cascade) and `R`
(per-replica-set cost) from measured throughput once benchmarks land
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Scenario = Literal["A", "B", "C"]


@dataclass(frozen=True)
class ScenarioParams:
    fixed_fleet_usd: float  # F: fixed 24h fleet cost (GPUs + platform)
    variable_per_1m: float  # V: $/1M tokens (egress, logs, S3, NAT)
    tokens_per_cascade_per_day: float  # C: tokens/day one cascade serves before scale-out
    replica_set_usd: float  # R: cost of each additional full GPU replica-set per day


# cost-formula table
_SCENARIOS: dict[Scenario, ScenarioParams] = {
    "A": ScenarioParams(70.0, 0.05, 30e6, 45.0),
    "B": ScenarioParams(230.0, 0.10, 80e6, 184.0),
    "C": ScenarioParams(510.0, 0.15, 80e6, 184.0),
}


def daily_cost(tokens: float, scenario: Scenario = "B") -> float:
    """Estimated USD for one day at ``tokens`` user-visible tokens

    Two-regime: a fixed fleet dominates below capacity; extra GPU replica-sets
    kick in above it.  daily = F + V*(T/1e6) + R*max(0, ceil(T/C) - 1)
    """
    p = _SCENARIOS[scenario]
    replicas = max(1, math.ceil(tokens / p.tokens_per_cascade_per_day))
    return (
        p.fixed_fleet_usd + p.variable_per_1m * (tokens / 1e6) + p.replica_set_usd * (replicas - 1)
    )


def dollars_per_1m_tokens(tokens: float, scenario: Scenario = "B") -> float:
    """Effective $/1M user tokens at a given daily volume (the amortization curve)."""
    if tokens <= 0:
        return float("inf")
    return daily_cost(tokens, scenario) / (tokens / 1e6)


# Reference aggregate HBM bandwidths (bytes/s) for the roofline floor
_HBM_BANDWIDTH: dict[str, float] = {
    "a10g": 600e9,
    "l4": 300e9,
    "l40s": 864e9,
    "h100": 3.35e12,
    "h200": 4.8e12,
}


def roofline_dollars_per_1m_tokens(
    *,
    weight_bytes: float,
    gpus: int,
    gpu: str,
    gpu_hourly_usd: float,
    mbu: float = 1.0,
) -> float:
    """Physics-floor $/1M tokens from the decode roofline

    Decode is memory-bandwidth-bound: min step time ~ weight_bytes / (gpus *
    per-GPU HBM bandwidth * MBU). tokens/s = 1/step; $/1M = hourly / (tok/s *
    3600) * 1e6.  A measured $/token far above this floor is an efficiency bug,
    not a pricing fact
    """
    bw = _HBM_BANDWIDTH[gpu.lower()] * gpus * mbu
    if bw <= 0:
        raise ValueError("aggregate bandwidth must be positive")
    step_time_s = weight_bytes / bw
    tokens_per_s = 1.0 / step_time_s
    dollars_per_token = (gpu_hourly_usd * gpus) / (tokens_per_s * 3600.0)
    return dollars_per_token * 1e6


@dataclass(frozen=True)
class RoutePrice:
    route: str
    input_per_1m: float
    output_per_1m: float

    def request_cost(self, input_tokens: int, output_tokens: int) -> float:
        return input_tokens / 1e6 * self.input_per_1m + output_tokens / 1e6 * self.output_per_1m


def price_route(
    *,
    route: str,
    gpu_hourly_usd: float,
    input_tokens_per_s: float,
    output_tokens_per_s: float,
) -> RoutePrice:
    """Derive $/1M input and output tokens for a route from GPU-hour cost /
    measured throughput. This is what routing thresholds must be built on
    — measured $/token per tier, not guesses"""
    if input_tokens_per_s <= 0 or output_tokens_per_s <= 0:
        raise ValueError("throughput must be positive")
    per_hour = gpu_hourly_usd
    input_per_1m = per_hour / (input_tokens_per_s * 3600) * 1e6
    output_per_1m = per_hour / (output_tokens_per_s * 3600) * 1e6
    return RoutePrice(route, input_per_1m, output_per_1m)


@dataclass(frozen=True)
class UnitEconomics:
    tokens_per_day: float
    scenario: Scenario
    daily_cost_usd: float
    dollars_per_1m_tokens: float
    replica_sets: int


def unit_economics(tokens_per_day: float, scenario: Scenario = "B") -> UnitEconomics:
    p = _SCENARIOS[scenario]
    replicas = max(1, math.ceil(tokens_per_day / p.tokens_per_cascade_per_day))
    return UnitEconomics(
        tokens_per_day=tokens_per_day,
        scenario=scenario,
        daily_cost_usd=round(daily_cost(tokens_per_day, scenario), 2),
        dollars_per_1m_tokens=round(dollars_per_1m_tokens(tokens_per_day, scenario), 4),
        replica_sets=replicas,
    )
