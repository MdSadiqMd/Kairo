"""Route and model selection.

Given a normalized request and a resolved budget, decide the route tier and the
concrete model role. This is deliberately a small, deterministic, auditable
rule engine — every decision is logged for eval and cost analysis, and
routing thresholds are meant to be recalibrated from measured $/token per tier,
not guessed. A learned classifier can slot in behind this same interface
later without changing callers.
"""

from __future__ import annotations

from dataclasses import dataclass

from router.budgets import BudgetSpec
from router.schemas import ChatCompletionRequest, Route


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    role: str  # model role to resolve in the registry
    reason: str


# Below this estimated prompt size and with no tools, a request is "simple"
# enough for the fast tier. Recalibrate from measured cost/quality.
FAST_PATH_TOKEN_THRESHOLD = 200


def decide_route(  # noqa: PLR0911 - a flat, auditable rule engine reads best as sequential returns
    req: ChatCompletionRequest,
    budget: BudgetSpec,
    *,
    input_tokens: int,
    tenant_cheap_mode: bool,
) -> RouteDecision:
    wants_tools = bool(req.tools)

    # Explicit high-effort modes always take the reasoner (and may run the agent
    # path when tools are involved).
    if budget.route == "reasoning":
        if wants_tools and budget.tools_allowed:
            return RouteDecision("agent", "reasoner", "deep/max mode with tools")
        return RouteDecision("reasoning", "reasoner", f"{budget.thinking_budget} thinking budget")

    # Cheap-mode tenants and trivially-small prompts take the fast model.
    if tenant_cheap_mode:
        return RouteDecision("fast", "fast", "tenant cheap mode")
    if not wants_tools and input_tokens < FAST_PATH_TOKEN_THRESHOLD and budget.route == "fast":
        return RouteDecision("fast", "fast", "below complexity threshold, no tools")

    # Tool-bearing normal requests go through the agent path.
    if wants_tools and budget.tools_allowed:
        return RouteDecision("agent", "reasoner", "tools requested")

    # Default: normal reasoning on the main reasoner.
    if budget.route == "fast":
        return RouteDecision("fast", "fast", "fast mode default")
    return RouteDecision("normal", "reasoner", "normal route default")
