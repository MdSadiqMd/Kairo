"""Router configuration.

Settings come from environment variables (12-factor); in AWS they are injected
by the External Secrets Operator and the Terraform-rendered ConfigMap. Nothing
here reaches out to the network at import time.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ROUTER_", extra="ignore")

    environment: str = "dev"
    log_level: str = "INFO"

    # Model registry source. In production this is DynamoDB; locally it is a
    # YAML file so the router runs without AWS.
    registry_backend: str = Field(default="file", pattern="^(file|dynamodb)$")
    registry_file: str = "ml/models/registry.local.yaml"
    registry_table: str = "kairo-dev-model-registry"
    registry_refresh_seconds: int = 30

    # Upstream (vLLM/SGLang) call behavior.
    upstream_connect_timeout_s: float = 5.0
    upstream_read_timeout_s: float = 120.0
    upstream_max_connections: int = 256
    upstream_max_retries: int = 1

    # Safety classifier service.
    safety_enabled: bool = True
    safety_url: str = "http://safety-classifier.kairo.svc.cluster.local:8080"
    safety_timeout_s: float = 2.0
    safety_fail_open: bool = False  # fail closed: if safety is down, block

    # Auth.
    auth_enabled: bool = True
    api_keys_secret: str = "kairo-dev-api-key"  # Secrets Manager id (prod)
    api_keys_file: str = ""  # local dev: path to JSON {key: tenant_id}

    # Event emission.
    events_enabled: bool = True
    events_backend: str = Field(default="stdout", pattern="^(stdout|kinesis|sqs)$")
    events_stream: str = "kairo-dev-inference-events"

    # Raw prompt/output capture for the training flywheel. Raw text is
    # attached to events ONLY when this is on AND the tenant has consented; the
    # redaction job downstream is the second gate before anything becomes
    # training-eligible.
    capture_raw_enabled: bool = False
    # Consent applied to tenants without an explicit per-tenant setting (the
    # keys file may specify {"tenant_id": ..., "training_consent": true}).
    default_training_consent: bool = False

    # Default token budgets (per-tenant overrides live in the registry).
    default_max_input_tokens: int = 32768
    default_max_output_tokens: int = 8192
    default_deadline_ms: int = 120_000

    # Cache-aware routing.
    cache_affinity_enabled: bool = True
    cache_queue_depth_failover: int = 32  # spill to least-loaded above this


@lru_cache
def get_settings() -> Settings:
    return Settings()
