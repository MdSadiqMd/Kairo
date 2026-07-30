"""Request/trace identifier helpers

``X-Request-ID`` propagation end-to-end: the router generates an id, forwards
it to the model server, and stamps it on events, logs, and traces so one grep
 goes from client complaint to GPU pod
"""

from __future__ import annotations

import uuid

REQUEST_ID_HEADER = "X-Request-ID"
TRACE_ID_HEADER = "X-Trace-ID"


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


def new_trace_id() -> str:
    return uuid.uuid4().hex


def new_proof_id() -> str:
    return f"proof_{uuid.uuid4().hex}"


def coerce_request_id(value: str | None) -> str:
    """Accept a caller-supplied id if present and sane, else mint a fresh one.

    Caller ids are length-bounded to keep them safe to log and to prevent
    unbounded-header abuse.
    """
    if value and 8 <= len(value) <= 128 and value.isascii():
        return value
    return new_request_id()
