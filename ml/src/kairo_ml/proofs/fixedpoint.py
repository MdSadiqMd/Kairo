from __future__ import annotations

import math


def isqrt_scaled(val: int, scale: int) -> int:
    if val <= 0:
        return 0
    x = math.isqrt(val * scale * scale)
    return x


def group_normalize_fixed(rewards: list[int], scale: int = 10**6) -> list[int]:
    n = len(rewards)
    if n < 2:
        return [0] * n
    total = sum(rewards)
    mean_fp = total * scale // n
    var_sum = sum((r * scale - mean_fp) ** 2 for r in rewards)
    var_fp = var_sum // n
    std_fp = isqrt_scaled(var_fp, 1)
    if std_fp == 0:
        return [0] * n
    return [((r * scale - mean_fp) * scale) // std_fp for r in rewards]
