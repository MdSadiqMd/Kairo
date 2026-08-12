"""Deployable online-RL cycle runner

This is the Kubernetes entry point that connects the tested online-loop control
logic to real artifacts

Supports two modes via ONLINE_RL_UPDATER env var:
- "artifact-only" (default): Debug mode, writes JSON without training
- "lora": Production mode, runs real LoRA/QLoRA adapter training

And two eval modes via ONLINE_RL_EVAL_MODE env var:
- "synthetic" (default): Uses env-configured pass rate for testing
- "real": Runs actual eval against candidate endpoint
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from kairo_common import get_logger

from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec
from kairo_ml.rl.online_loop import OnlineRLLoop, rollouts_from_scored
from kairo_ml.rl.policy_updaters import get_policy_updater

log = get_logger("online-rl-trainer")


@dataclass
class ConfigError:
    """Represents a configuration error"""

    var: str
    message: str
    fatal: bool = True


@dataclass
class ConfigValidationResult:
    """Result of configuration validation"""

    errors: list[ConfigError] = field(default_factory=list)
    warnings: list[ConfigError] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(e.fatal for e in self.errors)


def validate_required_env_vars() -> list[ConfigError]:
    """Validate required environment variables based on the configured mode"""
    errors: list[ConfigError] = []

    updater_mode = os.environ.get("ONLINE_RL_UPDATER", "artifact-only")
    eval_mode = os.environ.get("ONLINE_RL_EVAL_MODE", "synthetic")

    if updater_mode == "lora":
        base_model = os.environ.get("ONLINE_RL_BASE_MODEL", "")
        if not base_model:
            errors.append(
                ConfigError(
                    "ONLINE_RL_BASE_MODEL",
                    "ONLINE_RL_BASE_MODEL is required when ONLINE_RL_UPDATER=lora",
                )
            )

    if eval_mode == "real":
        candidate_endpoint = os.environ.get("ONLINE_RL_CANDIDATE_ENDPOINT", "")
        if not candidate_endpoint:
            errors.append(
                ConfigError(
                    "ONLINE_RL_CANDIDATE_ENDPOINT",
                    "ONLINE_RL_CANDIDATE_ENDPOINT is required when ONLINE_RL_EVAL_MODE=real",
                )
            )

    candidates_uri = os.environ.get("ONLINE_RL_CANDIDATES_URI", "")
    candidates_json = os.environ.get("ONLINE_RL_CANDIDATES_JSON", "")
    if not candidates_uri and not candidates_json:
        errors.append(
            ConfigError(
                "ONLINE_RL_CANDIDATES_URI",
                "Either ONLINE_RL_CANDIDATES_URI or ONLINE_RL_CANDIDATES_JSON must be set to provide training data",
                fatal=False,
            )
        )

    output_uri = os.environ.get("ONLINE_RL_OUTPUT_URI", "")
    if updater_mode == "artifact-only" and not output_uri:
        errors.append(
            ConfigError(
                "ONLINE_RL_OUTPUT_URI",
                "ONLINE_RL_OUTPUT_URI is recommended when ONLINE_RL_UPDATER=artifact-only (defaulting to /tmp)",
                fatal=False,
            )
        )

    return errors


def validate_s3_connectivity() -> list[ConfigError]:
    """Validate S3 bucket connectivity for configured S3 URIs"""
    errors: list[ConfigError] = []

    s3_uris: list[tuple[str, str]] = []

    candidates_uri = os.environ.get("ONLINE_RL_CANDIDATES_URI", "")
    if candidates_uri.startswith("s3://"):
        s3_uris.append(("ONLINE_RL_CANDIDATES_URI", candidates_uri))

    output_uri = os.environ.get("ONLINE_RL_OUTPUT_URI", "")
    if output_uri.startswith("s3://"):
        s3_uris.append(("ONLINE_RL_OUTPUT_URI", output_uri))

    result_uri = os.environ.get("ONLINE_RL_RESULT_URI", "")
    if result_uri.startswith("s3://"):
        s3_uris.append(("ONLINE_RL_RESULT_URI", result_uri))

    adapter_s3_uri = os.environ.get("ONLINE_RL_ADAPTER_S3_URI", "")
    if adapter_s3_uri.startswith("s3://"):
        s3_uris.append(("ONLINE_RL_ADAPTER_S3_URI", adapter_s3_uri))

    if not s3_uris:
        return errors

    try:
        import boto3
        from botocore.exceptions import ClientError

        endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
        s3 = boto3.client("s3", endpoint_url=endpoint_url)

        checked_buckets: set[str] = set()
        for var_name, uri in s3_uris:
            bucket = uri.removeprefix("s3://").split("/", 1)[0]
            if bucket in checked_buckets:
                continue
            checked_buckets.add(bucket)
            try:
                s3.head_bucket(Bucket=bucket)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                if error_code == "404":
                    errors.append(
                        ConfigError(
                            var_name,
                            f"S3 bucket '{bucket}' does not exist (referenced in {var_name})",
                        )
                    )
                elif error_code == "403":
                    errors.append(
                        ConfigError(
                            var_name,
                            f"Access denied to S3 bucket '{bucket}' (referenced in {var_name})",
                        )
                    )
                else:
                    errors.append(
                        ConfigError(
                            var_name,
                            f"Cannot access S3 bucket '{bucket}': {error_code} (referenced in {var_name})",
                        )
                    )
    except ImportError:
        errors.append(
            ConfigError(
                "boto3",
                "boto3 is required for S3 operations but is not installed",
            )
        )
    except Exception as e:
        errors.append(
            ConfigError(
                "AWS",
                f"Failed to initialize S3 client: {e}",
            )
        )

    return errors


def validate_zk_config() -> list[ConfigError]:
    """Validate ZK inference configuration"""
    errors: list[ConfigError] = []

    from kairo_ml.proofs.settings import zk_enabled

    if not zk_enabled():
        return errors

    proof_queue_url = os.environ.get("PROOF_QUEUE_URL", "")
    proof_queue_dir = os.environ.get("PROOF_QUEUE_DIR", "")

    if not proof_queue_url and not proof_queue_dir:
        errors.append(
            ConfigError(
                "PROOF_QUEUE_URL",
                "ZK_INFERENCE=true requires either PROOF_QUEUE_URL (SQS) or PROOF_QUEUE_DIR (local) to be set",
            )
        )

    if proof_queue_url:
        try:
            import boto3
            from botocore.exceptions import ClientError

            endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
            sqs = boto3.client("sqs", endpoint_url=endpoint_url)
            try:
                sqs.get_queue_attributes(QueueUrl=proof_queue_url, AttributeNames=["QueueArn"])
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                errors.append(
                    ConfigError(
                        "PROOF_QUEUE_URL",
                        f"Cannot access SQS queue at PROOF_QUEUE_URL: {error_code}",
                    )
                )
        except ImportError:
            pass
        except Exception as e:
            errors.append(
                ConfigError(
                    "PROOF_QUEUE_URL",
                    f"Failed to validate PROOF_QUEUE_URL: {e}",
                )
            )

    return errors


def validate_config(*, skip_connectivity: bool = False) -> ConfigValidationResult:
    """Validate all configuration

    Args:
        skip_connectivity: If True, skip S3/SQS connectivity checks (for fast validation)

    Returns:
        ConfigValidationResult with all errors and warnings
    """
    result = ConfigValidationResult()

    env_errors = validate_required_env_vars()
    for err in env_errors:
        if err.fatal:
            result.errors.append(err)
        else:
            result.warnings.append(err)

    if not skip_connectivity:
        result.errors.extend(validate_s3_connectivity())

    result.errors.extend(validate_zk_config())

    return result


def log_validation_result(result: ConfigValidationResult) -> None:
    """Log validation errors and warnings"""
    for warning in result.warnings:
        log.warning(
            "config warning",
            extra={"var": warning.var, "detail": warning.message},
        )

    for error in result.errors:
        log.error(
            "config error",
            extra={"var": error.var, "detail": error.message},
        )


def fail_on_invalid_config(result: ConfigValidationResult) -> None:
    """Exit with error if configuration is invalid"""
    if not result.valid:
        log_validation_result(result)
        log.error(
            "aborting due to configuration errors",
            extra={"error_count": len([e for e in result.errors if e.fatal])},
        )
        sys.exit(1)
    elif result.warnings:
        log_validation_result(result)


def read_candidates() -> list[dict]:
    inline = os.environ.get("ONLINE_RL_CANDIDATES_JSON")
    if inline:
        return json.loads(inline)
    uri = os.environ.get("ONLINE_RL_CANDIDATES_URI", "")
    if not uri:
        return []
    text = read_text(uri)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def read_text(uri: str) -> str:
    if uri.startswith("s3://"):
        import boto3

        bucket, key = uri.removeprefix("s3://").split("/", 1)
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode()
    return Path(uri).read_text()


def write_json(uri: str, payload: dict) -> None:
    data = json.dumps(payload, indent=2, sort_keys=True).encode()
    if uri.startswith("s3://"):
        import boto3

        bucket, key = uri.removeprefix("s3://").split("/", 1)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data)
        return
    path = Path(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def synthetic_evaluator() -> EvalRun:
    """Synthetic evaluator for testing. Uses env-configured pass rate."""
    n = int(os.environ.get("ONLINE_RL_EVAL_N", "10"))
    pass_rate = float(os.environ.get("ONLINE_RL_EVAL_PASS_RATE", "1.0"))
    passes = int(n * pass_rate)
    items = [
        ItemResult(item_id=str(i), passed=i < passes, latency_ms=10, cost_usd=0.0) for i in range(n)
    ]
    return EvalRun(
        eval_run_id=f"online-rl-{int(time.time())}",
        suite=os.environ.get("ONLINE_RL_EVAL_SUITE", "smoke_v1"),
        model=os.environ.get("ONLINE_RL_MODEL", "model-32b"),
        model_version=os.environ.get("ONLINE_RL_CANDIDATE_VERSION", "candidate"),
        items=items,
    )


def real_evaluator() -> EvalRun:
    """Real evaluator that runs against the candidate endpoint"""
    from kairo_ml.rl.evaluator import evaluator_from_config

    evaluator = evaluator_from_config()
    candidate_version = os.environ.get("ONLINE_RL_CANDIDATE_VERSION", "candidate")
    return evaluator.evaluate_candidate(candidate_version)


def get_baseline_eval() -> EvalRun | None:
    """Get baseline eval run if baseline endpoint is configured"""
    mode = os.environ.get("ONLINE_RL_EVAL_MODE", "synthetic")
    if mode != "real":
        return None
    baseline_endpoint = os.environ.get("ONLINE_RL_BASELINE_ENDPOINT")
    if not baseline_endpoint:
        return None
    from kairo_ml.rl.evaluator import evaluator_from_config

    evaluator = evaluator_from_config()
    return evaluator.evaluate_baseline()


def get_evaluator():
    """Factory for evaluator based on ONLINE_RL_EVAL_MODE env var"""
    mode = os.environ.get("ONLINE_RL_EVAL_MODE", "synthetic")
    if mode == "real":
        return real_evaluator
    return synthetic_evaluator


def main(argv: list[str] | None = None) -> int:
    """Main entry point for online RL trainer

    Configuration via environment variables:
    - ONLINE_RL_UPDATER: "artifact-only" or "lora" (default: artifact-only)
    - ONLINE_RL_EVAL_MODE: "synthetic" or "real" (default: synthetic)
    - ONLINE_RL_OUTPUT_URI: Where to write candidate artifacts
    - ONLINE_RL_RESULT_URI: Where to write cycle result
    - ONLINE_RL_CANDIDATES_URI: S3 or file URI with scored candidates
    - ONLINE_RL_POLICY_STEP: Current policy version
    - ONLINE_RL_MIN_PASS_RATE: Gate threshold
    - ONLINE_RL_MAX_STALENESS: Max policy step drift allowed

    Command-line flags:
    - --validate-config: Validate configuration and exit (0=valid, 1=invalid)
    - --skip-connectivity: Skip S3/SQS connectivity checks during validation
    """
    parser = argparse.ArgumentParser(prog="online_trainer")
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Validate configuration and exit without running the training cycle",
    )
    parser.add_argument(
        "--skip-connectivity",
        action="store_true",
        help="Skip S3/SQS connectivity checks during validation",
    )
    args = parser.parse_args(argv)

    if args.validate_config:
        result = validate_config(skip_connectivity=args.skip_connectivity)
        log_validation_result(result)
        if result.valid:
            log.info("configuration valid")
            return 0
        else:
            log.error(
                "configuration invalid",
                extra={"error_count": len([e for e in result.errors if e.fatal])},
            )
            return 1

    validation_result = validate_config()
    fail_on_invalid_config(validation_result)

    result_uri = os.environ.get("ONLINE_RL_RESULT_URI", "/tmp/online-rl/result.json")
    policy_step = int(os.environ.get("ONLINE_RL_POLICY_STEP", "0"))

    log.info(
        "starting online RL cycle",
        extra={
            "updater": os.environ.get("ONLINE_RL_UPDATER", "artifact-only"),
            "eval_mode": os.environ.get("ONLINE_RL_EVAL_MODE", "synthetic"),
            "policy_step": policy_step,
        },
    )

    candidates = read_candidates()
    rollouts = rollouts_from_scored(candidates, default_policy_step=policy_step)

    spec = PromotionGateSpec(
        min_pass_rate=float(os.environ.get("ONLINE_RL_MIN_PASS_RATE", "0.5")),
        min_detectable_effect=float(os.environ.get("ONLINE_RL_MIN_EFFECT", "0.0")),
        min_n=int(os.environ.get("ONLINE_RL_MIN_N", "10")),
        max_safety_regression=float(os.environ.get("ONLINE_RL_MAX_SAFETY_REGRESSION", "0.01")),
    )

    updater = get_policy_updater()
    evaluator = get_evaluator()

    loop = OnlineRLLoop(
        spec=spec,
        updater=updater,
        evaluator=evaluator,
        policy_step=policy_step,
        max_staleness=int(os.environ.get("ONLINE_RL_MAX_STALENESS", "1")),
    )

    baseline = get_baseline_eval()
    cycle_result = loop.run_cycle(rollouts, baseline=baseline)

    log.info(
        "online RL cycle complete",
        extra={"accepted": cycle_result.accepted, "reason": cycle_result.reason},
    )

    result_payload: dict = {"accepted": cycle_result.accepted, "reason": cycle_result.reason}

    from kairo_ml.proofs.settings import zk_enabled

    if zk_enabled():
        from kairo_ml.proofs import witness
        from kairo_ml.proofs.jobs import DirProofJobSink, SqsProofJobSink

        queue_url = os.environ.get("PROOF_QUEUE_URL", "")
        artifacts_uri = os.environ.get("PROOF_ARTIFACTS_URI", "")
        if queue_url:
            sink = SqsProofJobSink(queue_url, artifacts_uri)
        else:
            proof_dir = os.environ.get("PROOF_QUEUE_DIR", "/tmp/proof-jobs")
            sink = DirProofJobSink(proof_dir)
        cycle_ref = witness.commit_cycle(
            rollouts,
            cycle_result,
            policy_step=policy_step,
            max_staleness=loop.max_staleness,
            spec=spec,
            baseline=baseline,
            sink=sink,
        )
        if cycle_ref:
            result_payload.update(cycle_ref)
            log.info("zk cycle committed", extra=cycle_ref)

    write_json(result_uri, result_payload)

    if cycle_result.accepted:
        promote_accepted_adapter(loop.policy_step)

    return 0 if cycle_result.accepted or cycle_result.reason == "no_onpolicy_samples" else 1


def promote_accepted_adapter(new_policy_step: int) -> None:
    """Promote the accepted adapter to the registry and trigger rollout"""
    from kairo_ml.evals.promote import DynamoDBRegistryStore, trigger_deployment_rollout
    from kairo_ml.rl.artifacts import read_adapter_manifest

    output_dir = os.environ.get("ONLINE_RL_OUTPUT_DIR", "/tmp/online-rl/adapter")
    adapter_s3_uri = os.environ.get("ONLINE_RL_ADAPTER_S3_URI", "")
    registry_table = os.environ.get("MODEL_REGISTRY_TABLE", "kairo-model-registry")
    namespace = os.environ.get("KAIRO_NAMESPACE", "kairo")
    model_name = os.environ.get("ONLINE_RL_MODEL", "reasoner-candidate")
    role = os.environ.get("ONLINE_RL_ROLE", "reasoner")

    manifest_path = Path(output_dir) / "adapter_manifest.json"
    if not manifest_path.exists():
        log.warning("No adapter manifest found, skipping promotion")
        return

    manifest = read_adapter_manifest(manifest_path)
    adapter_id = manifest.adapter_id
    adapter_uri = adapter_s3_uri or f"file://{output_dir}"

    registry = DynamoDBRegistryStore(registry_table)
    registry.update_adapter(model_name, role, adapter_id, adapter_uri, new_policy_step)
    log.info(
        "adapter promoted to registry",
        extra={"adapter_id": adapter_id, "policy_version": new_policy_step},
    )

    deployment_name = os.environ.get("ONLINE_RL_DEPLOYMENT", f"vllm-{role}-candidate")
    trigger_deployment_rollout(namespace, deployment_name, adapter_uri, new_policy_step)


if __name__ == "__main__":
    raise SystemExit(main())
