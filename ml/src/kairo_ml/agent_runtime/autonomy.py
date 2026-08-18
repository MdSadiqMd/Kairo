"""Contextual autonomy gate

Called before every risky action. It reuses the exact risk-table semantics of
services/safety_classifier/src/safety_classifier/policy.py
(RuleAutonomyPolicy): the ten canonical rows below are kept byte-for-byte
consistent with that service's _AUTONOMY_TABLE so the runtime and the safety
service can never disagree on what "read secrets" or "modify IAM" means. (That
service is a separate workspace package, not an ml dependency, so the table
is replicated here rather than imported — this module is the single place they
are asserted equal)

The gate turns a policy verdict into an actionable decision for the worker loop:

- allow     -> action proceeds.
- block     -> action refused; feedback + safer alternative returned so the
                   parent agent can pick another path *without* interrupting the
                   user (return feedback to the parent agent).
- ask_user  -> needs human approval; if an approver callback is wired and
                   approves, it proceeds, otherwise it is held (not allowed) and
                   surfaced as feedback.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from kairo_common import get_logger

logger = get_logger(__name__)

AutonomyDecision = Literal["allow", "ask_user", "block"]
RiskLevel = Literal["low", "medium", "high", "critical"]

ApprovalCallback = Callable[[str, str | None], bool]


@dataclass(frozen=True)
class AutonomyVerdict:
    decision: AutonomyDecision
    risk_level: RiskLevel
    reason: str
    safer_alternative: str | None = None


class AutonomyPolicy(Protocol):
    def classify_action(self, *, action: str, target: str | None) -> AutonomyVerdict: ...


# The ten canonical rows are identical to the safety service's table.
_CANONICAL_TABLE: dict[str, tuple[AutonomyDecision, RiskLevel, str]] = {
    "read_secrets": ("block", "critical", "Block unless explicitly authorized"),
    "write_production_data": ("ask_user", "high", "Human approval required"),
    "external_network_call": ("ask_user", "medium", "Allowlist or review"),
    "install_dependency": ("allow", "low", "Allowed if registry approved"),
    "delete_files": ("ask_user", "medium", "Review depending on path"),
    "modify_iam": ("ask_user", "critical", "Human approval required"),
    "modify_security_config": ("ask_user", "critical", "Human approval required"),
    "send_message": ("ask_user", "high", "Human approval required"),
    "financial_action": ("ask_user", "critical", "Human approval required"),
    "legal_action": ("ask_user", "critical", "Human approval required"),
}

# Extensions for sandbox-local tool actions absent from the service table. These
# never override a canonical row; they only classify low-risk, sandbox-scoped
# operations the worker loop performs (reads, scratch writes, sandboxed commands).
_EXTENSION_TABLE: dict[str, tuple[AutonomyDecision, RiskLevel, str]] = {
    "read_file": ("allow", "low", "Local read within the sandbox"),
    "write_scratch": ("allow", "low", "Sandbox-scoped scratch write"),
    "run_command": ("allow", "low", "Sandboxed command execution"),
}

_AUTONOMY_TABLE = {**_CANONICAL_TABLE, **_EXTENSION_TABLE}

_SCRATCH_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/")


class RuleAutonomyPolicy:
    """Deterministic risk-table policy consistent with the safety service."""

    def classify_action(self, *, action: str, target: str | None) -> AutonomyVerdict:
        decision, risk, reason = _AUTONOMY_TABLE.get(
            action, ("ask_user", "medium", "unknown action; defaulting to human review")
        )
        # Path-sensitive refinement (mirrors the safety service): destructive or
        # write actions confined to a scratch path are low risk.
        if (
            action in {"delete_files", "write_production_data"}
            and target
            and target.startswith(_SCRATCH_PREFIXES)
        ):
            return AutonomyVerdict("allow", "low", "scratch path", None)

        safer = _safer_alternative(action) if decision != "allow" else None
        return AutonomyVerdict(decision, risk, reason, safer)


def _safer_alternative(action: str) -> str:
    hints = {
        "read_secrets": "read from an injected, scoped credential broker instead of raw secrets",
        "write_production_data": "write to a sandbox/scratch location and request human review",
        "external_network_call": "use an allowlisted mirror or a cached artifact",
        "delete_files": "move to a quarantine directory instead of deleting",
        "modify_iam": "propose the IAM change as a reviewable diff for a human",
        "modify_security_config": "propose the change as a reviewable diff for a human",
        "send_message": "draft the message and hand it to the user for confirmation",
        "financial_action": "prepare the transaction as a draft requiring approval",
        "legal_action": "prepare the action as a draft requiring approval",
    }
    return hints.get(action, "surface to the user for confirmation")


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    verdict: AutonomyVerdict
    feedback: str

    def as_dict(self) -> dict[str, Any]:
        """The classifier output shape."""
        return {
            "decision": self.verdict.decision,
            "risk_level": self.verdict.risk_level,
            "reason": self.verdict.reason,
            "safer_alternative": self.verdict.safer_alternative,
        }


class AutonomyGate:
    """Wraps an AutonomyPolicy and resolves ask_user against an optional
    human-approval callback into a concrete allow/hold decision"""

    def __init__(
        self,
        policy: AutonomyPolicy | None = None,
        *,
        approver: ApprovalCallback | None = None,
    ) -> None:
        self._policy = policy or RuleAutonomyPolicy()
        self._approver = approver

    def evaluate(self, *, action: str, target: str | None = None) -> GateDecision:
        verdict = self._policy.classify_action(action=action, target=target)

        if verdict.decision == "allow":
            allowed = True
        elif verdict.decision == "block":
            allowed = False
        else:  # ask_user
            allowed = bool(self._approver and self._approver(action, target))

        feedback = "" if allowed else _build_feedback(action, verdict)
        if not allowed:
            logger.info(
                "autonomy gate held action",
                extra={
                    "action": action,
                    "autonomy_decision": verdict.decision,
                    "risk_level": verdict.risk_level,
                },
            )
        return GateDecision(allowed=allowed, verdict=verdict, feedback=feedback)


def _build_feedback(action: str, verdict: AutonomyVerdict) -> str:
    base = f"action '{action}' -> {verdict.decision} ({verdict.risk_level}): {verdict.reason}"
    if verdict.safer_alternative:
        base += f" | safer alternative: {verdict.safer_alternative}"
    return base
