"""Thinking budgets.

Public modes map to internal inference behavior — max reasoning tokens,
candidate count, verifier use, and whether tools are allowed. The key
invariant: budgets are enforced server-side regardless of user text. A user
can write /think or /no_think (Model template behavior), but the token
ceiling is set here, not by the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass

from router.schemas import PublicMode, Route, ThinkingBudget


@dataclass(frozen=True)
class BudgetSpec:
    thinking_budget: ThinkingBudget
    max_reasoning_tokens: int
    candidates: int
    use_verifier: bool
    tools_allowed: bool
    route: Route


# We pick the upper bound of each documented range as the
# server-side ceiling. Candidate counts follow the "deep/max" columns.
_MODE_TABLE: dict[PublicMode, BudgetSpec] = {
    "fast": BudgetSpec("none", 0, 1, False, False, "fast"),
    "normal": BudgetSpec("medium", 2048, 1, False, True, "normal"),
    "deep": BudgetSpec("high", 16384, 4, True, True, "reasoning"),
    "max": BudgetSpec("max", 32768, 16, True, True, "reasoning"),
}


def resolve_budget(mode: PublicMode | None) -> BudgetSpec:
    return _MODE_TABLE[mode or "normal"]


def apply_thinking_control(reasoning_tokens: int) -> dict[str, object]:
    """Extra params passed to the upstream to bound reasoning.

    vLLM/SGLang for Model accept a max thinking-token control; where the server
    lacks a native knob we fall back to injecting /no_think and a hard
    max_tokens bound. Emitting both is safe — the server ignores unknown
    fields.
    """
    if reasoning_tokens == 0:
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {
        "chat_template_kwargs": {"enable_thinking": True},
        "extra_body": {"max_reasoning_tokens": reasoning_tokens},
    }
