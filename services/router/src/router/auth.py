"""API-key authentication and tenant resolution.

Keys map to tenants. In production keys come from Secrets Manager (rotated,
injected by the External Secrets Operator); locally they come from a JSON file
so the router runs without AWS. Comparison is constant-time to avoid leaking key
material through timing.
"""

from __future__ import annotations

import hmac
import json
from pathlib import Path

from kairo_common import ErrorCode, PlatformError, get_logger

log = get_logger(__name__)


class Tenant:
    def __init__(
        self,
        tenant_id: str,
        *,
        cheap_mode: bool = False,
        training_consent: bool | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.cheap_mode = cheap_mode
        # None means "no explicit setting" — the router falls back to
        # ROUTER_DEFAULT_TRAINING_CONSENT.
        self.training_consent = training_consent


class Authenticator:
    def __init__(self, *, enabled: bool, keys: dict[str, object]) -> None:
        self._enabled = enabled
        # Store as list of (key, tenant) for constant-time scan; dict lookup on
        # the raw key would be timing-variable and leak validity.
        self._keys = list(keys.items())

    @classmethod
    def from_file(cls, path: str, *, enabled: bool) -> Authenticator:
        keys: dict[str, object] = {}
        if path and Path(path).exists():
            keys = json.loads(Path(path).read_text())
        return cls(enabled=enabled, keys=keys)

    def authenticate(self, authorization: str | None) -> Tenant:
        if not self._enabled:
            return Tenant("local-dev")
        token = _extract_bearer(authorization)
        matched: object | None = None
        # Scan every key so runtime does not depend on which key matched.
        for key, tenant_spec in self._keys:
            if hmac.compare_digest(key, token):
                matched = tenant_spec
        if matched is None:
            raise PlatformError(ErrorCode.AUTHENTICATION_FAILED, "invalid or missing API key")
        # The keys file maps key -> tenant_id string, or key -> object with
        # per-tenant settings ({"tenant_id": ..., "training_consent": true}).
        if isinstance(matched, dict):
            return Tenant(
                str(matched["tenant_id"]),
                cheap_mode=bool(matched.get("cheap_mode", False)),
                training_consent=matched.get("training_consent"),
            )
        return Tenant(str(matched))


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise PlatformError(ErrorCode.AUTHENTICATION_FAILED, "missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise PlatformError(ErrorCode.AUTHENTICATION_FAILED, "malformed Authorization header")
    return parts[1].strip()
