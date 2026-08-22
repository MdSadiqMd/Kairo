"""Tests for online_trainer configuration validation."""

from __future__ import annotations

import os
from unittest.mock import patch

from kairo_ml.rl.online_trainer import (
    ConfigError,
    ConfigValidationResult,
    main,
    validate_config,
    validate_required_env_vars,
    validate_zk_config,
)


class TestValidateRequiredEnvVars:
    """Tests for validate_required_env_vars."""

    def test_default_mode_no_errors(self) -> None:
        """Default artifact-only mode with synthetic eval requires no special config."""
        with patch.dict(os.environ, {}, clear=True):
            errors = validate_required_env_vars()
        warnings = [e for e in errors if not e.fatal]
        fatal = [e for e in errors if e.fatal]
        assert len(fatal) == 0
        assert any("ONLINE_RL_CANDIDATES_URI" in e.var for e in warnings)

    def test_lora_mode_requires_base_model(self) -> None:
        """LoRA mode requires ONLINE_RL_BASE_MODEL."""
        with patch.dict(os.environ, {"ONLINE_RL_UPDATER": "lora"}, clear=True):
            errors = validate_required_env_vars()
        fatal = [e for e in errors if e.fatal]
        assert any("ONLINE_RL_BASE_MODEL" in e.var for e in fatal)

    def test_lora_mode_with_base_model_ok(self) -> None:
        """LoRA mode with base model set passes."""
        env = {
            "ONLINE_RL_UPDATER": "lora",
            "ONLINE_RL_BASE_MODEL": "Qwen/Qwen2.5-0.5B",
            "ONLINE_RL_CANDIDATES_JSON": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            errors = validate_required_env_vars()
        fatal = [e for e in errors if e.fatal]
        assert len(fatal) == 0

    def test_real_eval_requires_candidate_endpoint(self) -> None:
        """Real eval mode requires ONLINE_RL_CANDIDATE_ENDPOINT."""
        with patch.dict(os.environ, {"ONLINE_RL_EVAL_MODE": "real"}, clear=True):
            errors = validate_required_env_vars()
        fatal = [e for e in errors if e.fatal]
        assert any("ONLINE_RL_CANDIDATE_ENDPOINT" in e.var for e in fatal)

    def test_real_eval_with_endpoint_ok(self) -> None:
        """Real eval mode with endpoint set passes."""
        env = {
            "ONLINE_RL_EVAL_MODE": "real",
            "ONLINE_RL_CANDIDATE_ENDPOINT": "http://localhost:8000",
            "ONLINE_RL_CANDIDATES_JSON": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            errors = validate_required_env_vars()
        fatal = [e for e in errors if e.fatal]
        assert len(fatal) == 0

    def test_candidates_json_satisfies_requirement(self) -> None:
        """ONLINE_RL_CANDIDATES_JSON satisfies the candidates requirement."""
        env = {"ONLINE_RL_CANDIDATES_JSON": '[{"reward": 1}]'}
        with patch.dict(os.environ, env, clear=True):
            errors = validate_required_env_vars()
        assert not any("ONLINE_RL_CANDIDATES_URI" in e.var for e in errors)


class TestValidateZkConfig:
    """Tests for validate_zk_config."""

    def test_zk_disabled_no_errors(self) -> None:
        """ZK disabled requires no proof queue config."""
        with patch.dict(os.environ, {"ZK_INFERENCE": "false"}, clear=True):
            errors = validate_zk_config()
        assert len(errors) == 0

    def test_zk_enabled_requires_proof_queue(self) -> None:
        """ZK enabled requires PROOF_QUEUE_URL or PROOF_QUEUE_DIR."""
        from kairo_ml.proofs.settings import zk_enabled

        zk_enabled.cache_clear()
        try:
            with patch.dict(os.environ, {"ZK_INFERENCE": "true"}, clear=True):
                errors = validate_zk_config()
            assert any("PROOF_QUEUE_URL" in e.var for e in errors)
        finally:
            zk_enabled.cache_clear()

    def test_zk_enabled_with_dir_ok(self) -> None:
        """ZK enabled with PROOF_QUEUE_DIR passes."""
        from kairo_ml.proofs.settings import zk_enabled

        zk_enabled.cache_clear()
        try:
            env = {"ZK_INFERENCE": "true", "PROOF_QUEUE_DIR": "/tmp/proofs"}
            with patch.dict(os.environ, env, clear=True):
                errors = validate_zk_config()
            assert len(errors) == 0
        finally:
            zk_enabled.cache_clear()


class TestValidateConfig:
    """Tests for the top-level validate_config function."""

    def test_valid_minimal_config(self) -> None:
        """Minimal valid config with candidates."""
        env = {"ONLINE_RL_CANDIDATES_JSON": "[]"}
        with patch.dict(os.environ, env, clear=True):
            result = validate_config(skip_connectivity=True)
        assert result.valid

    def test_collects_warnings(self) -> None:
        """Non-fatal errors become warnings."""
        with patch.dict(os.environ, {}, clear=True):
            result = validate_config(skip_connectivity=True)
        assert result.valid
        assert len(result.warnings) > 0


class TestConfigValidationResult:
    """Tests for ConfigValidationResult."""

    def test_valid_when_no_fatal_errors(self) -> None:
        """Result is valid when no fatal errors exist."""
        result = ConfigValidationResult()
        result.warnings.append(ConfigError("X", "warning", fatal=False))
        assert result.valid

    def test_invalid_when_fatal_error(self) -> None:
        """Result is invalid when any fatal error exists."""
        result = ConfigValidationResult()
        result.errors.append(ConfigError("X", "fatal error", fatal=True))
        assert not result.valid


class TestMainValidateConfigFlag:
    """Tests for --validate-config CLI flag."""

    def test_validate_config_returns_0_on_valid(self) -> None:
        """--validate-config returns 0 for valid config."""
        env = {"ONLINE_RL_CANDIDATES_JSON": "[]"}
        with patch.dict(os.environ, env, clear=True):
            result = main(["--validate-config", "--skip-connectivity"])
        assert result == 0

    def test_validate_config_returns_1_on_invalid(self) -> None:
        """--validate-config returns 1 for invalid config."""
        from kairo_ml.proofs.settings import zk_enabled

        zk_enabled.cache_clear()
        try:
            env = {"ZK_INFERENCE": "true"}
            with patch.dict(os.environ, env, clear=True):
                result = main(["--validate-config", "--skip-connectivity"])
            assert result == 1
        finally:
            zk_enabled.cache_clear()
