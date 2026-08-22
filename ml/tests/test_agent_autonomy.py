from __future__ import annotations

from kairo_ml.agent_runtime.autonomy import AutonomyGate, RuleAutonomyPolicy


def test_gate_blocks_read_secrets() -> None:
    gate = AutonomyGate()
    decision = gate.evaluate(action="read_secrets")
    assert not decision.allowed
    assert decision.verdict.decision == "block"
    assert decision.verdict.risk_level == "critical"
    assert decision.feedback


def test_gate_holds_modify_iam_without_approver() -> None:
    gate = AutonomyGate()
    decision = gate.evaluate(action="modify_iam")
    # ask_user with no human in the loop -> not allowed, with a safer alternative.
    assert not decision.allowed
    assert decision.verdict.decision == "ask_user"
    assert decision.verdict.safer_alternative


def test_gate_allows_scratch_writes() -> None:
    gate = AutonomyGate()
    assert gate.evaluate(action="write_scratch", target="notes.txt").allowed
    # Path-sensitive refinement: deleting inside a scratch path is low risk.
    assert gate.evaluate(action="delete_files", target="/tmp/build").allowed
    # Production writes are still held.
    assert not gate.evaluate(action="write_production_data", target="/prod/db").allowed


def test_gate_approver_can_authorize_ask_user() -> None:
    gate = AutonomyGate(approver=lambda _action, _target: True)
    assert gate.evaluate(action="send_message").allowed


def test_gate_output_shape_matches_spec() -> None:
    gate = AutonomyGate()
    payload = gate.evaluate(action="read_secrets").as_dict()
    assert set(payload) == {"decision", "risk_level", "reason", "safer_alternative"}
    assert payload["decision"] == "block"


def test_policy_table_consistent_with_safety_service_rows() -> None:
    # The ten canonical rows must match services/safety_classifier policy.py.
    policy = RuleAutonomyPolicy()
    expected = {
        "read_secrets": ("block", "critical"),
        "write_production_data": ("ask_user", "high"),
        "external_network_call": ("ask_user", "medium"),
        "install_dependency": ("allow", "low"),
        "delete_files": ("ask_user", "medium"),
        "modify_iam": ("ask_user", "critical"),
        "modify_security_config": ("ask_user", "critical"),
        "send_message": ("ask_user", "high"),
        "financial_action": ("ask_user", "critical"),
        "legal_action": ("ask_user", "critical"),
    }
    for action, (decision, risk) in expected.items():
        verdict = policy.classify_action(action=action, target=None)
        assert (verdict.decision, verdict.risk_level) == (decision, risk), action
