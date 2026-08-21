from __future__ import annotations

import pytest
from kairo_common import PlatformError
from router.auth import Authenticator
from router.budgets import apply_thinking_control, resolve_budget
from router.cache_routing import ConsistentHashRouter, stable_prefix_key
from router.model_registry import ModelEntry, ModelRegistry
from router.quota import QuotaManager
from router.routing import decide_route
from router.schemas import ChatCompletionRequest, ChatMessage
from router.streaming import StreamTally, sanitize_stream
from router.tokens import estimate_message_tokens


def _req(**kw) -> ChatCompletionRequest:
    kw.setdefault("model", "model-32b")
    kw.setdefault("messages", [ChatMessage(role="user", content="hello world")])
    return ChatCompletionRequest(**kw)


def test_budget_modes_map_to_specs() -> None:
    assert resolve_budget("fast").candidates == 1
    assert resolve_budget("fast").max_reasoning_tokens == 0
    assert resolve_budget("deep").use_verifier is True
    assert resolve_budget("max").candidates == 16
    # Unknown/None defaults to normal.
    assert resolve_budget(None).route == "normal"


def test_thinking_control_disables_thinking_for_fast() -> None:
    ctrl = apply_thinking_control(0)
    assert ctrl["chat_template_kwargs"] == {"enable_thinking": False}
    ctrl = apply_thinking_control(4096)
    assert ctrl["extra_body"]["max_reasoning_tokens"] == 4096


def test_routing_fast_path_for_small_no_tools() -> None:
    d = decide_route(
        _req(mode="fast"), resolve_budget("fast"), input_tokens=10, tenant_cheap_mode=False
    )
    assert d.route == "fast"


def test_routing_reasoning_with_tools_goes_agent() -> None:
    req = _req(mode="deep", tools=[{"type": "function", "function": {"name": "x"}}])
    d = decide_route(req, resolve_budget("deep"), input_tokens=10, tenant_cheap_mode=False)
    assert d.route == "agent"
    assert d.role == "reasoner"


def test_routing_cheap_mode_forces_fast() -> None:
    d = decide_route(
        _req(mode="normal"), resolve_budget("normal"), input_tokens=10, tenant_cheap_mode=True
    )
    assert d.route == "fast"


def test_token_estimate_rounds_up() -> None:
    n = estimate_message_tokens([ChatMessage(role="user", content="a" * 40)])
    # 40 chars / 4 + per-message overhead
    assert n == 10 + 4


def test_registry_resolves_by_name_and_role() -> None:
    entries = [
        ModelEntry(
            name="model-8b",
            role="fast",
            version="v1",
            endpoint="http://fast",
            served_model_id="MODEL_PROVIDER/Model-8B",
            max_model_len=32768,
        ),
        ModelEntry(
            name="model-32b",
            role="reasoner",
            version="v1",
            endpoint="http://reason",
            served_model_id="MODEL_PROVIDER/Model-32B",
            max_model_len=16384,
        ),
    ]
    reg = ModelRegistry(entries)
    assert reg.resolve(name="model-8b", role="reasoner").role == "fast"  # name wins
    assert reg.resolve(name=None, role="reasoner").name == "model-32b"
    with pytest.raises(PlatformError):
        reg.resolve(name=None, role="nonexistent")


def test_registry_hides_undeployable() -> None:
    entries = [
        ModelEntry(
            name="candidate",
            role="reasoner",
            version="v2",
            endpoint="http://c",
            served_model_id="c",
            max_model_len=1024,
            deployable=False,
        )
    ]
    reg = ModelRegistry(entries)
    assert reg.list_public() == []


def test_auth_constant_time_and_tenant_mapping() -> None:
    auth = Authenticator(enabled=True, keys={"sk-abc": "acme", "sk-def": "globex"})
    assert auth.authenticate("Bearer sk-def").tenant_id == "globex"
    with pytest.raises(PlatformError):
        auth.authenticate("Bearer wrong")
    with pytest.raises(PlatformError):
        auth.authenticate(None)
    with pytest.raises(PlatformError):
        auth.authenticate("Token sk-abc")


def test_auth_disabled_returns_local_tenant() -> None:
    auth = Authenticator(enabled=False, keys={})
    assert auth.authenticate(None).tenant_id == "local-dev"


def test_quota_rate_limit_trips() -> None:
    q = QuotaManager(rate=0.0, burst=2.0)
    q.check_rate("t", now=0.0)
    q.check_rate("t", now=0.0)
    with pytest.raises(PlatformError):
        q.check_rate("t", now=0.0)


def test_quota_context_guard() -> None:
    with pytest.raises(PlatformError):
        QuotaManager.check_context(100, 10, max_input=50, max_model_len=1000)
    with pytest.raises(PlatformError):
        QuotaManager.check_context(900, 200, max_input=1000, max_model_len=1000)
    QuotaManager.check_context(100, 100, max_input=1000, max_model_len=1000)


def test_consistent_hash_stable_and_rebalances() -> None:
    r = ConsistentHashRouter(replicas=4)
    key = stable_prefix_key("system prompt", "acme")
    a = r.preferred_replica(key)
    b = r.preferred_replica(key)
    assert a == b  # deterministic
    assert 0 <= a < 4


def test_cache_router_fails_over_when_saturated() -> None:
    r = ConsistentHashRouter(replicas=3)
    key = stable_prefix_key("sys", "acme")
    pref = r.preferred_replica(key)
    depths = [0, 0, 0]
    depths[pref] = 100
    picked = r.pick(key, queue_depths=depths, failover_threshold=32)
    assert picked != pref  # spilled to a least-loaded replica


async def test_stream_strips_chain_of_thought() -> None:
    async def upstream():
        chunks = [
            b'data: {"choices":[{"delta":{"reasoning_content":"secret thinking"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
            b'"usage":{"completion_tokens":3}}\n\n',
            b"data: [DONE]\n\n",
        ]
        for c in chunks:
            yield c

    tally = StreamTally()
    out = b"".join([chunk async for chunk in sanitize_stream(upstream(), tally)])
    assert b"secret thinking" not in out
    assert b"Hello" in out
    assert b"[DONE]" in out
    assert tally.output_tokens == 3
    assert tally.finish_reason == "stop"
