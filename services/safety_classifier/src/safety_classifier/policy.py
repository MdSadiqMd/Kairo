"""Deterministic first-pass safety policy.

The MVP ships a deterministic classifier ("policy interface with
deterministic first implementation") so the eval gate and abuse controls exist
before a trained safety model does. Everything is expressed behind the
InputPolicy / OutputPolicy / AutonomyPolicy interfaces so a
configured model-derived policy model can replace the rules without touching the
router contract.

Design choices that matter:
- Prompt-injection defense: retrieved/tool content is untrusted;
  we flag injection markers in the latest turn.
- Secret exposure: block requests that appear to be exfiltrating credentials.
- Autonomy: a risk table maps tool actions to allow/ask_user/block
  independent of the model's own judgment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol

Decision = Literal["allow", "review", "block"]
AutonomyDecision = Literal["allow", "ask_user", "block"]
RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class InputVerdict:
    decision: Decision
    task_type: str = "general"
    reason: str = ""


@dataclass(frozen=True)
class OutputVerdict:
    decision: Decision
    reason: str = ""
    redactions: int = 0


@dataclass(frozen=True)
class AutonomyVerdict:
    decision: AutonomyDecision
    risk_level: RiskLevel
    reason: str
    safer_alternative: str | None = None


_INJECTION_PATTERNS = [
    re.compile(r"ignore\b.{0,40}\b(instruction|prompt)", re.I),
    re.compile(r"disregard\b.{0,40}\b(system|developer|instruction|prompt)", re.I),
    re.compile(r"you are now (in )?developer mode", re.I),
    re.compile(r"reveal\b.{0,30}\b(system prompt|instructions|hidden)", re.I),
    re.compile(r"</?(system|tool|assistant)>", re.I),
]

_SECRET_EXFIL_PATTERNS = [
    re.compile(
        r"\b(print|show|output|leak|reveal)\b.{0,30}\b(secret|api[_ -]?key|password|token)\b", re.I
    ),
    re.compile(r"aws_secret_access_key", re.I),
]

# Illustrative harmful-intent markers. A real deployment replaces this with a
# policy model; the interface is what matters here.
_HIGH_RISK_MARKERS = [
    re.compile(r"\b(synthesi[sz]e|manufacture)\b.{0,40}\b(nerve agent|bioweapon|sarin)\b", re.I),
    re.compile(r"\bstep[- ]by[- ]step\b.{0,40}\b(build|make)\b.{0,20}\b(bomb|explosive)\b", re.I),
]

_SECRET_VALUE_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style key
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),  # GitHub PAT
]

_TASK_HINTS = {
    "coding": re.compile(r"\b(code|function|bug|stack ?trace|compile|python|rust|java)\b", re.I),
    "math": re.compile(r"\b(prove|integral|equation|theorem|solve for)\b", re.I),
    "sql": re.compile(r"\b(select|insert|update|delete)\b.{0,20}\bfrom\b", re.I),
}


def _classify_task(text: str) -> str:
    for name, pat in _TASK_HINTS.items():
        if pat.search(text):
            return name
    return "general"


# --- Policy interfaces + deterministic implementations ----------------------


class InputPolicy(Protocol):
    def classify_input(
        self, *, latest_user_text: str, full_text: str, has_tools: bool
    ) -> InputVerdict: ...


class OutputPolicy(Protocol):
    def classify_output(self, *, text: str) -> OutputVerdict: ...


class AutonomyPolicy(Protocol):
    def classify_action(self, *, action: str, target: str | None) -> AutonomyVerdict: ...


class RuleInputPolicy:
    def classify_input(
        self, *, latest_user_text: str, full_text: str, has_tools: bool
    ) -> InputVerdict:
        task = _classify_task(full_text)
        for pat in _HIGH_RISK_MARKERS:
            if pat.search(full_text):
                return InputVerdict("block", task, "high-risk content policy")
        for pat in _SECRET_EXFIL_PATTERNS:
            if pat.search(full_text):
                return InputVerdict("block", task, "credential exfiltration attempt")
        for pat in _INJECTION_PATTERNS:
            if pat.search(latest_user_text):
                # Injection is suspicious but often benign phrasing — review, not block.
                return InputVerdict("review", task, "possible prompt injection")
        return InputVerdict("allow", task)


class RuleOutputPolicy:
    def classify_output(self, *, text: str) -> OutputVerdict:
        redactions = sum(len(p.findall(text)) for p in _SECRET_VALUE_PATTERNS)
        if redactions:
            return OutputVerdict("review", "secret material in output", redactions)
        return OutputVerdict("allow")


# Autonomy risk table. Keys are canonical action names emitted by the
# agent runtime; the parent agent uses the verdict to choose a safer path.
_AUTONOMY_TABLE: dict[str, tuple[AutonomyDecision, RiskLevel, str]] = {
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


class RuleAutonomyPolicy:
    def classify_action(self, *, action: str, target: str | None) -> AutonomyVerdict:
        decision, risk, reason = _AUTONOMY_TABLE.get(
            action, ("ask_user", "medium", "unknown action; defaulting to human review")
        )
        # Path-sensitive refinement: deleting inside a scratch dir is low risk.
        if action == "delete_files" and target and target.startswith("/tmp/"):
            return AutonomyVerdict("allow", "low", "scratch path", None)
        safer = "surface to user for confirmation" if decision == "ask_user" else None
        return AutonomyVerdict(decision, risk, reason, safer)
