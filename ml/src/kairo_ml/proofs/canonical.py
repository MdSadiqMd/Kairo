from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

SCALE = 10**6


def canonical_json(obj: Any) -> bytes:
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _reject_floats(obj: Any) -> None:
    if isinstance(obj, float):
        raise TypeError(f"floats are banned from canonical form; got {obj!r}")
    if isinstance(obj, dict):
        for v in obj.values():
            _reject_floats(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _reject_floats(v)


def to_fixed(x: float, scale: int = SCALE) -> int:
    result = Decimal(repr(x)) * Decimal(scale)
    return int(result.to_integral_value(rounding=ROUND_HALF_EVEN))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def commit(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def commit_sequence(hex_digests: list[str]) -> str:
    raw = b"".join(bytes.fromhex(h) for h in hex_digests)
    return sha256_hex(raw)
