"""Redaction pipeline

The primary model-privacy defense: PII, secrets, credentials, and tenant-private
content are removed before anything becomes training-eligible ("what never
enters the corpus can never be memorized"). This is the ingestion
gate the flow: PII → secret → tenant policy → consent → license →
redacted event, feeding the training-candidate queue

The detectors here are deterministic (regex + entropy); Macie + a custom NER
model augment them in production. A record that fails consent or license policy
is dropped entirely, not merely masked
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")
_GENERIC_KEY = re.compile(r"\b(?:sk|pk|ghp|xoxb|AIza)[-_A-Za-z0-9]{16,}\b")
_HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9+/=_-]{24,}\b")

_ENTROPY_THRESHOLD = 4.0  # bits/char; typical secrets exceed this


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


@dataclass
class RedactionReport:
    pii_removed: int = 0
    secrets_removed: int = 0
    dropped: bool = False
    drop_reason: str | None = None
    detectors: dict[str, int] = field(default_factory=dict)

    def _bump(self, name: str, n: int) -> None:
        if n:
            self.detectors[name] = self.detectors.get(name, 0) + n


def _mask_all(pattern: re.Pattern[str], text: str, token: str) -> tuple[str, int]:
    count = 0

    def repl(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return token

    return pattern.sub(repl, text), count


def redact_text(text: str, report: RedactionReport) -> str:
    for pat, token, kind in [
        (_PRIVATE_KEY, "[REDACTED_PRIVATE_KEY]", "secret"),
        (_AWS_KEY, "[REDACTED_AWS_KEY]", "secret"),
        (_GENERIC_KEY, "[REDACTED_KEY]", "secret"),
        (_SSN, "[REDACTED_SSN]", "pii"),
        (_CREDIT_CARD, "[REDACTED_CC]", "pii"),
        (_EMAIL, "[REDACTED_EMAIL]", "pii"),
        (_PHONE, "[REDACTED_PHONE]", "pii"),
    ]:
        text, n = _mask_all(pat, text, token)
        report._bump(pat.pattern[:16], n)
        if kind == "secret":
            report.secrets_removed += n
        else:
            report.pii_removed += n

    # Entropy pass: catch bearer tokens / API keys the regexes miss
    def entropy_repl(m: re.Match[str]) -> str:
        tok = m.group(0)
        if shannon_entropy(tok) >= _ENTROPY_THRESHOLD:
            report.secrets_removed += 1
            report._bump("high_entropy", 1)
            return "[REDACTED_SECRET]"
        return tok

    text = _HIGH_ENTROPY_TOKEN.sub(entropy_repl, text)
    return text


@dataclass
class TenantPolicy:
    training_opt_in: bool = False
    allowed_licenses: frozenset[str] = frozenset({"mit", "apache-2.0", "bsd-3-clause", "cc0"})


class RedactionPipeline:
    """pipeline as a single callable over a raw inference event."""

    def __init__(self, policy: TenantPolicy) -> None:
        self._policy = policy

    def process(self, event: dict[str, Any]) -> tuple[dict[str, Any] | None, RedactionReport]:
        report = RedactionReport()

        # Consent gate: training is opt-in only. No consent → drop
        if not (event.get("training_consent") and self._policy.training_opt_in):
            report.dropped = True
            report.drop_reason = "no_training_consent"
            return None, report

        # License gate for code payloads
        license_id = (event.get("license") or "").lower()
        if license_id and license_id not in self._policy.allowed_licenses:
            report.dropped = True
            report.drop_reason = f"license_not_allowed:{license_id}"
            return None, report

        redacted = dict(event)
        for field_name in ("prompt_raw", "output_raw"):
            value = event.get(field_name)
            if isinstance(value, str):
                redacted[field_name] = redact_text(value, report)
        return redacted, report
