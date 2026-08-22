from __future__ import annotations

from kairo_ml.rl_envs import Action, available, make
from kairo_ml.rl_envs.math_env import MathEnv, equivalent
from kairo_ml.rl_envs.sql_env import SqlEnv
from kairo_ml.rl_envs.tool_use import ToolUseEnv


def test_registry_lists_all_envs() -> None:
    assert set(available()) == {"browser", "code_repair", "math", "sql", "tool_use"}


def test_math_equivalence_helpers() -> None:
    assert equivalent("1/2", "0.5")
    assert equivalent("x+x", "2*x")
    assert equivalent("0.25 + 0.25", "1/2")
    assert not equivalent("1/3", "0.5")
    assert not equivalent("x", "2*x")
    assert not equivalent("import os", "0")  # unparseable -> rejected


def test_math_env_accepts_and_rejects() -> None:
    with MathEnv() as env:
        env.reset("sum_halves")
        _obs, reward, done, info = env.step(Action(kind="submit", content="0.5"))
        assert done
        assert reward.value == 1.0
        assert info["correct"]
        assert env.score().passed

    with MathEnv() as env:
        env.reset("expand_double")
        env.step(Action(kind="submit", content="3*x"))  # wrong
        report = env.score()
        assert not report.passed
        assert report.reward == 0.0


def test_sql_env_matches_on_hidden_fixture() -> None:
    with SqlEnv() as env:
        env.reset("active_users")
        env.step(
            Action(kind="submit", content="SELECT id FROM users WHERE status='active' ORDER BY id")
        )
        assert env.score().passed


def test_sql_env_rejects_wrong_query() -> None:
    with SqlEnv() as env:
        env.reset("active_users")
        env.step(Action(kind="submit", content="SELECT id FROM users"))  # missing filter
        report = env.score()
        assert not report.passed
        assert report.reward == 0.0


def test_sql_env_rejects_broken_query() -> None:
    with SqlEnv() as env:
        env.reset("top_customer")
        env.step(Action(kind="submit", content="SELECT nope FROM nonexistent"))
        assert not env.score().passed


def test_tool_use_catches_unauthorized_action() -> None:
    with ToolUseEnv() as env:
        env.reset("provision_account")
        # Authorized: reach the goal status.
        env.step(Action(kind="set_status", args={"value": "active"}))
        # Unauthorized: touch the protected `admin` key.
        _obs, reward, _done, info = env.step(
            Action(kind="set", args={"key": "admin", "value": True})
        )
        assert info["unauthorized"]
        assert reward.value == 0.0
        report = env.score()
        assert not report.passed
        assert any("unauthorized_action" in f for f in report.hacking_flags)


def test_tool_use_passes_when_authorized_only() -> None:
    with ToolUseEnv() as env:
        env.reset("provision_account")
        env.step(Action(kind="set_status", args={"value": "active"}))
        env.step(Action(kind="submit"))
        report = env.score()
        assert report.passed
        assert not report.hacking_flags


def test_browser_env_reaches_goal() -> None:
    env = make("browser")
    try:
        env.reset("login_flow")
        env.step(Action(kind="type", args={"element": "#username", "text": "ada"}))
        env.step(Action(kind="click", args={"element": "#login"}))
        assert env.score().passed
    finally:
        env.cleanup()


def test_browser_env_fails_without_actions() -> None:
    env = make("browser")
    try:
        env.reset("login_flow")
        assert not env.score().passed
    finally:
        env.cleanup()


def test_transcript_is_append_only_and_audits_leak() -> None:
    with MathEnv() as env:
        env.reset("sum_halves")
        env.step(Action(kind="submit", content="the answer is 1/2"))
        entries = env.transcript.entries
        seqs = [e.seq for e in entries]
        assert seqs == list(range(len(entries)))  # ordered, contiguous
        leaks = env.transcript.audit_answer_leak(["1/2"])
        assert leaks  # the submitted action contained the oracle string
