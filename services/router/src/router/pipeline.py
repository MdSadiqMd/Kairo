"""Request orchestration (sequence + routing).

One class, RouterService, owns the request lifecycle so it can be unit-tested
without a running FastAPI server:

    authenticate → enforce quota + token budget → normalize → classify safety →
    choose route/model/budget → call model server (stream or candidates+verifier)
    → emit structured event.

Streaming and non-streaming share everything up to the upstream call.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from kairo_common import (
    InferenceEvent,
    get_logger,
    new_trace_id,
    safety_blocked,
)
from kairo_common.logging import request_context

from router.auth import Tenant
from router.budgets import apply_thinking_control, resolve_budget
from router.cache_routing import ConsistentHashRouter, stable_prefix_key
from router.config import Settings
from router.model_registry import ModelEntry, ModelRegistry
from router.quota import QuotaManager
from router.routing import decide_route
from router.safety import SafetyClient
from router.schemas import ChatCompletionRequest, RequestContext
from router.streaming import StreamTally, sanitize_stream
from router.telemetry import (
    CACHE_ROUTED,
    E2E_LATENCY,
    OUTPUT_TOKENS,
    REQUESTS,
    SAFETY_BLOCKS,
    EventSink,
    prompt_hash,
)
from router.tokens import estimate_message_tokens
from router.upstream import UpstreamClient
from router.verifier import VerifierClient

log = get_logger(__name__)


@dataclass
class PreparedRequest:
    ctx: RequestContext
    entry: ModelEntry
    body: dict
    started: float
    prompt_text: str = ""
    training_consent: bool = False


class RouterService:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ModelRegistry,
        quota: QuotaManager,
        safety: SafetyClient,
        upstream: UpstreamClient,
        verifier: VerifierClient,
        event_sink: EventSink,
    ) -> None:
        self._s = settings
        self._registry = registry
        self._quota = quota
        self._safety = safety
        self._upstream = upstream
        self._verifier = verifier
        self._events = event_sink
        self._cache_router = ConsistentHashRouter(replicas=1)

    async def prepare(
        self, req: ChatCompletionRequest, tenant: Tenant, request_id: str
    ) -> PreparedRequest:
        """Everything up to the upstream call. Raises PlatformError on rejection."""
        started = time.monotonic()
        self._quota.check_rate(tenant.tenant_id)

        budget = resolve_budget(req.mode)
        input_tokens = estimate_message_tokens(req.messages)

        # Safety runs before routing so a block short-circuits compute.
        verdict = await self._safety.classify(
            req, tenant_id=tenant.tenant_id, request_id=request_id
        )
        if verdict.decision == "block":
            SAFETY_BLOCKS.labels(decision="block").inc()
            raise safety_blocked(verdict.reason or "blocked by safety policy")
        if verdict.decision == "review":
            SAFETY_BLOCKS.labels(decision="review").inc()

        decision = decide_route(
            req, budget, input_tokens=input_tokens, tenant_cheap_mode=tenant.cheap_mode
        )
        entry = self._registry.resolve(name=req.model, role=decision.role)

        max_output = req.resolved_max_output_tokens(self._s.default_max_output_tokens)
        self._quota.check_context(
            input_tokens,
            max_output,
            max_input=self._s.default_max_input_tokens,
            max_model_len=entry.max_model_len,
        )

        prefix = _system_prefix(req)
        cache_key = (
            stable_prefix_key(prefix, tenant.tenant_id) if self._s.cache_affinity_enabled else ""
        )

        ctx = RequestContext(
            request_id=request_id,
            tenant_id=tenant.tenant_id,
            user_id=req.user,
            model_requested=req.model,
            route=decision.route,
            thinking_budget=budget.thinking_budget,
            safety_level=verdict.decision,
            max_input_tokens=self._s.default_max_input_tokens,
            max_output_tokens=max_output,
            deadline_ms=self._s.default_deadline_ms,
            trace_id=new_trace_id(),
            target_model=entry.name,
            target_model_version=entry.version,
            candidates=budget.candidates,
            use_verifier=budget.use_verifier,
            tools_allowed=budget.tools_allowed,
            cache_prefix_key=cache_key,
        )

        body = _build_upstream_body(req, entry, max_output, budget.max_reasoning_tokens)

        # Resolve training consent for the flywheel. Raw capture only
        # happens when BOTH the global toggle is on AND the tenant has consented
        # (explicit tenant setting > global default).
        effective_consent = (
            tenant.training_consent
            if tenant.training_consent is not None
            else self._s.default_training_consent
        )
        capture_raw = self._s.capture_raw_enabled and effective_consent

        # Serialize the user-visible prompt (system + user messages) for the
        # event — never the internal body we send upstream.
        prompt_text = _serialize_prompt(req) if capture_raw else ""

        return PreparedRequest(
            ctx=ctx,
            entry=entry,
            body=body,
            started=started,
            prompt_text=prompt_text,
            training_consent=effective_consent,
        )

    async def complete(self, prep: PreparedRequest, req: ChatCompletionRequest) -> dict:
        """Non-streaming path, with optional candidate sampling + verifier rerank."""
        with request_context(
            request_id=prep.ctx.request_id,
            tenant_id=prep.ctx.tenant_id,
            route=prep.ctx.route,
            model_version=prep.ctx.target_model_version,
        ):
            if prep.ctx.candidates > 1 and prep.ctx.use_verifier:
                response = await self._sample_and_rerank(prep, req)
            else:
                response = await self._upstream.chat_completion(
                    prep.entry.endpoint, prep.body, request_id=prep.ctx.request_id
                )
            output_text = _first_content(response) if prep.training_consent else ""
            self._finish(prep, response=response, output_text=output_text)
            return response

    async def stream(self, prep: PreparedRequest) -> AsyncIterator[bytes]:
        """Streaming path — always a single candidate; CoT is stripped."""
        tally = StreamTally()
        with request_context(
            request_id=prep.ctx.request_id,
            tenant_id=prep.ctx.tenant_id,
            route=prep.ctx.route,
            model_version=prep.ctx.target_model_version,
        ):
            upstream = self._upstream.stream_chat_completion(
                prep.entry.endpoint, prep.body, request_id=prep.ctx.request_id
            )
            async for out in sanitize_stream(upstream, tally):
                yield out
            output_text = tally.output_text if prep.training_consent else ""
            self._finish(prep, tally=tally, output_text=output_text)

    async def _sample_and_rerank(self, prep: PreparedRequest, req: ChatCompletionRequest) -> dict:
        best_response: dict | None = None
        texts: list[str] = []
        responses: list[dict] = []
        # Cap candidates to keep tail latency bounded; the budget already sets N.
        for _ in range(prep.ctx.candidates):
            resp = await self._upstream.chat_completion(
                prep.entry.endpoint,
                {**prep.body, "temperature": 0.8},
                request_id=prep.ctx.request_id,
            )
            responses.append(resp)
            texts.append(_first_content(resp))
        verifier_entry = self._safe_resolve_role("verifier")
        if verifier_entry is None:
            best_response = responses[0]
        else:
            prompt = _system_prefix(req)
            best_idx, scores = await self._verifier.rerank(
                verifier_entry.endpoint,
                prompt=prompt,
                candidates=texts,
                served_model_id=verifier_entry.served_model_id,
            )
            best_response = responses[best_idx]
            prep.ctx.__dict__["_verifier_score"] = scores[best_idx]
        return best_response

    def _safe_resolve_role(self, role: str) -> ModelEntry | None:
        try:
            return self._registry.resolve(name=None, role=role)
        except Exception:
            return None

    def _finish(
        self,
        prep: PreparedRequest,
        *,
        response: dict | None = None,
        tally: StreamTally | None = None,
        output_text: str = "",
    ) -> None:
        elapsed = time.monotonic() - prep.started
        ctx = prep.ctx
        if response is not None:
            usage = response.get("usage", {})
            output_tokens = usage.get("completion_tokens", 0)
            input_tokens = usage.get("prompt_tokens", 0)
            finish = _finish_reason(response)
        else:
            assert tally is not None
            output_tokens = tally.output_tokens
            input_tokens = 0
            finish = tally.finish_reason
        REQUESTS.labels(route=ctx.route, model=ctx.target_model, outcome="ok").inc()
        E2E_LATENCY.labels(route=ctx.route, model=ctx.target_model).observe(elapsed)
        OUTPUT_TOKENS.labels(route=ctx.route, model=ctx.target_model).observe(output_tokens)
        self._emit_event(
            prep, input_tokens, output_tokens, int(elapsed * 1000), finish, output_text
        )

    def _emit_event(
        self,
        prep: PreparedRequest,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        finish: str | None,
        output_text: str = "",
    ) -> None:
        if not self._s.events_enabled:
            return
        ctx = prep.ctx
        event = InferenceEvent(
            request_id=ctx.request_id,
            timestamp=_now_iso(),
            tenant_id=ctx.tenant_id,
            route=ctx.route,
            model=ctx.target_model,
            model_version=ctx.target_model_version,
            prompt_hash=prompt_hash(ctx.cache_prefix_key or ctx.request_id),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            finish_reason=finish
            if finish in {"stop", "length", "tool_calls", "content_filter", "error"}
            else None,
            safety_decision=ctx.safety_level,
            verifier_score=ctx.__dict__.get("_verifier_score"),
            training_consent=prep.training_consent,
            policy_version=prep.entry.policy_version,
            prompt_raw=prep.prompt_text or None,
            output_raw=output_text or None,
        )
        try:
            self._events.emit(event)
        except Exception:
            log.warning("event emit failed", exc_info=True)

    def cache_pick(self, prefix_key: str, queue_depths: list[int] | None) -> int:
        idx = self._cache_router.pick(
            prefix_key,
            queue_depths=queue_depths,
            failover_threshold=self._s.cache_queue_depth_failover,
        )
        CACHE_ROUTED.labels(outcome="affinity" if queue_depths is None else "checked").inc()
        return idx


def _system_prefix(req: ChatCompletionRequest) -> str:
    parts = [
        m.content
        for m in req.messages
        if m.role in {"system", "developer"} and isinstance(m.content, str)
    ]
    return "\n".join(parts)


def _serialize_prompt(req: ChatCompletionRequest) -> str:
    """Serialize the user-visible conversation for the training flywheel."""
    import json

    return json.dumps(
        [m.model_dump(exclude_none=True) for m in req.messages],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _build_upstream_body(
    req: ChatCompletionRequest, entry: ModelEntry, max_output: int, reasoning_tokens: int
) -> dict:
    body: dict = {
        "model": entry.served_model_id,
        "messages": [m.model_dump(exclude_none=True) for m in req.messages],
        "max_tokens": max_output,
    }
    if req.temperature is not None:
        body["temperature"] = req.temperature
    if req.top_p is not None:
        body["top_p"] = req.top_p
    if req.stop is not None:
        body["stop"] = req.stop
    if req.tools:
        body["tools"] = req.tools
        if req.tool_choice is not None:
            body["tool_choice"] = req.tool_choice
    thinking = apply_thinking_control(reasoning_tokens)
    if "chat_template_kwargs" in thinking:
        body["chat_template_kwargs"] = thinking["chat_template_kwargs"]
    extra_body = thinking.get("extra_body")
    if isinstance(extra_body, dict):
        body.update(extra_body)  # server-side reasoning bound
    return body


def _first_content(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content") or ""


def _finish_reason(response: dict) -> str | None:
    choices = response.get("choices", [])
    return choices[0].get("finish_reason") if choices else None


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
