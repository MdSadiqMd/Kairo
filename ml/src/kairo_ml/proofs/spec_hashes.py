from __future__ import annotations

import functools
import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from kairo_ml.proofs.canonical import SCALE, commit, to_fixed

if TYPE_CHECKING:
    from kairo_ml.proofs.witness import LoraDriftBounds


def _source_hash(module) -> str:
    src = Path(module.__file__).read_bytes()
    return hashlib.sha256(src).hexdigest()


@functools.cache
def reward_spec_hash() -> str:
    from kairo_ml.rl import rewards

    spec = {
        "name": "kairo_reward",
        "version": 1,
        "scale": SCALE,
        "constants": {
            "R_ACCEPT": to_fixed(rewards.R_ACCEPT),
            "R_REJECT": to_fixed(rewards.R_REJECT),
            "R_NEUTRAL": to_fixed(rewards.R_NEUTRAL),
            "EDIT_PERSISTENCE_BONUS": to_fixed(rewards.EDIT_PERSISTENCE_BONUS),
            "FOLLOWUP_DISSATISFACTION_PENALTY": to_fixed(rewards.FOLLOWUP_DISSATISFACTION_PENALTY),
        },
        "outcomes": ["accepted", "rejected", "shown_no_action", "not_shown"],
        "source_sha256": _source_hash(rewards),
    }
    return commit(spec)


@functools.cache
def grpo_spec_hash() -> str:
    from kairo_ml.proofs import fixedpoint
    from kairo_ml.rl import grpo

    spec = {
        "name": "grpo_group_norm_pop_std",
        "version": 1,
        "scale": SCALE,
        "degenerate_rule": "zeros_if_n_lt_2_or_std_eq_0",
        "grpo_source_sha256": _source_hash(grpo),
        "fixedpoint_source_sha256": _source_hash(fixedpoint),
    }
    return commit(spec)


def gate_spec_hash(spec) -> str:
    from kairo_ml.evals import gate as gate_mod
    from kairo_ml.evals import statistics as stats_mod

    gate_spec_dict = {
        "name": "promotion_gate",
        "version": 1,
        "scale": SCALE,
        "min_pass_rate": to_fixed(spec.min_pass_rate),
        "significance_level": to_fixed(spec.significance_level),
        "min_detectable_effect": to_fixed(spec.min_detectable_effect),
        "min_n": spec.min_n,
        "max_safety_regression": to_fixed(spec.max_safety_regression),
        "max_cost_increase": to_fixed(spec.max_cost_increase),
        "max_latency_p99_ms": spec.max_latency_p99_ms,
        "comparison": spec.comparison,
        "bootstrap_iterations": 10000,
        "bootstrap_seed": 12345,
        "gate_source_sha256": _source_hash(gate_mod),
        "statistics_source_sha256": _source_hash(stats_mod),
    }
    return commit(gate_spec_dict)


def lora_drift_spec_hash(bounds: LoraDriftBounds) -> str:
    """Hash the LoRA drift bounds spec for proof binding.

    The spec captures the allowed magnitude/structure constraints that the
    adapter must satisfy relative to the base model (Phase 5 of the RL
    cryptography design).
    """
    spec_dict = {
        "name": "lora_drift",
        "version": 1,
        "scale": SCALE,
        "max_l2_norm": to_fixed(bounds.max_l2_norm),
        "max_delta": to_fixed(bounds.max_delta),
        "max_rank": bounds.max_rank,
        "allowed_modules": sorted(bounds.allowed_modules) if bounds.allowed_modules else None,
    }
    return commit(spec_dict)


@functools.cache
def rag_evidence_spec_hash() -> str:
    spec = {
        "name": "rag_evidence",
        "version": 1,
        "scale": SCALE,
        "min_relevance_score": to_fixed(0.0),
        "max_relevance_score": to_fixed(1.0),
    }
    return commit(spec)
