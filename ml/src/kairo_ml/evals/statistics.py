"""Eval statistics

A gate on a raw point estimate flaps: on small eval sets the same model passes
or fails on resampling noise. This module makes gates statistical:

- Wilson score interval for a pass rate (better small-n coverage than the
  normal approximation, and never leaves [0, 1])
- Paired bootstrap for the delta between a candidate and the current prod
  baseline on the *same* items — the correct comparison because eval items vary
  wildly in difficulty, and pairing cancels that variance
- Sample size for a target minimum detectable effect (MDE) so a registry
  entry can declare "n is large enough to catch a 1% regression at 80% power"

Pure-Python and dependency-free (stdlib random/math/statistics), so
it runs anywhere the eval runner runs, including inside the fast per-cycle
gate the real-time RL loop needs
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

Z_95 = 1.959963984540054  # two-sided 95%
Z_80_POWER = 0.8416212335729143  # one-sided z for 80% power


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float
    n: int


def wilson_interval(successes: int, n: int, z: float = Z_95) -> Interval:
    """Wilson score confidence interval for a binomial proportion."""
    if n == 0:
        return Interval(0.0, 0.0, 1.0, 0)
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / denom
    return Interval(p, max(0.0, center - margin), min(1.0, center + margin), n)


@dataclass(frozen=True)
class PairedDelta:
    """Candidate minus baseline mean delta with a bootstrap CI."""

    delta: float
    low: float
    high: float
    n: int
    prob_regression: float  # bootstrap P(delta < 0)


def paired_bootstrap_delta(
    baseline: list[float],
    candidate: list[float],
    *,
    iterations: int = 10_000,
    confidence: float = 0.95,
    seed: int = 12345,
) -> PairedDelta:
    """Bootstrap the mean paired delta (candidate[i] - baseline[i]).

    ``seed`` is fixed so the same inputs give the same verdict — gates must be
    reproducible (fix seeds and decoding params across runs).
    """
    if len(baseline) != len(candidate):
        raise ValueError("paired comparison requires equal-length, aligned score lists")
    n = len(baseline)
    if n == 0:
        return PairedDelta(0.0, 0.0, 0.0, 0, 0.5)
    diffs = [c - b for b, c in zip(baseline, candidate, strict=True)]
    observed = sum(diffs) / n

    rng = random.Random(seed)
    means: list[float] = []
    regressions = 0
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += diffs[rng.randrange(n)]
        m = total / n
        means.append(m)
        if m < 0:
            regressions += 1
    means.sort()
    lo_idx = int((1 - confidence) / 2 * iterations)
    hi_idx = int((1 + confidence) / 2 * iterations) - 1
    return PairedDelta(
        delta=observed,
        low=means[lo_idx],
        high=means[hi_idx],
        n=n,
        prob_regression=regressions / iterations,
    )


def required_n_for_mde(
    baseline_rate: float, mde: float, *, alpha: float = 0.05, power: float = 0.80
) -> int:
    """Approximate per-arm sample size to detect an absolute change ``mde`` in a
    proportion at the given alpha/power (normal approximation)."""
    z_alpha = Z_95 if alpha == 0.05 else _z_from_alpha(alpha)
    z_beta = Z_80_POWER if power == 0.80 else _z_from_power(power)
    p = min(max(baseline_rate, 1e-6), 1 - 1e-6)
    variance = 2 * p * (1 - p)
    n = ((z_alpha + z_beta) ** 2) * variance / (mde * mde)
    return math.ceil(n)


def _z_from_alpha(alpha: float) -> float:
    return _inv_norm(1 - alpha / 2)


def _z_from_power(power: float) -> float:
    return _inv_norm(power)


def _inv_norm(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    p_low = 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= 1 - p_low:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )
