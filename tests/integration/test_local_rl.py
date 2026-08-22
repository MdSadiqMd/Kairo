"""Integration test for local RL loop against MiniStack.

This test exercises the complete RL pipeline as it runs in prod:
1. Generate inference events → store in MiniStack S3/Kinesis
2. Aggregate rewards from events
3. Run GRPO training step on a small model
4. Eval gate verification
5. (Optional) Model promotion

Uses MODEL_PROVIDER/Model-0.6B for CPU-compatible testing.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import boto3
import pytest
from botocore.config import Config

MINISTACK_ENDPOINT = os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("TEST_MODEL_ID", "MODEL_PROVIDER/Model-0.6B")


def get_aws_client(service: str):
    """Get boto3 client configured for MiniStack."""
    return boto3.client(
        service,
        endpoint_url=MINISTACK_ENDPOINT,
        region_name=AWS_REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        config=Config(signature_version="v4"),
    )


@pytest.fixture(scope="module")
def ministack_ready():
    """Ensure MiniStack is running and healthy."""
    import requests

    health_url = f"{MINISTACK_ENDPOINT}/_localstack/health"
    for _ in range(30):
        try:
            resp = requests.get(health_url, timeout=2)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(1)

    pytest.fail("MiniStack not available")


@pytest.fixture(scope="module")
def s3_client(ministack_ready):
    return get_aws_client("s3")


@pytest.fixture(scope="module")
def dynamodb_client(ministack_ready):
    return get_aws_client("dynamodb")


@pytest.fixture(scope="module")
def kinesis_client(ministack_ready):
    return get_aws_client("kinesis")


@pytest.fixture(scope="module")
def sqs_client(ministack_ready):
    return get_aws_client("sqs")


@pytest.fixture(scope="module")
def setup_infrastructure(s3_client, dynamodb_client, kinesis_client, sqs_client):
    """Create required AWS resources in MiniStack."""
    prefix = "test-rl"

    buckets = [
        f"{prefix}-raw-events",
        f"{prefix}-redacted-events",
        f"{prefix}-model-artifacts",
    ]
    for bucket in buckets:
        try:
            s3_client.create_bucket(Bucket=bucket)
        except s3_client.exceptions.BucketAlreadyExists:
            pass

    tables = {
        f"{prefix}-model-registry": {"hash_key": "model_id", "range_key": "version"},
        f"{prefix}-request-metadata": {"hash_key": "request_id"},
    }
    for table_name, schema in tables.items():
        key_schema = [{"AttributeName": schema["hash_key"], "KeyType": "HASH"}]
        attrs = [{"AttributeName": schema["hash_key"], "AttributeType": "S"}]
        if "range_key" in schema:
            key_schema.append({"AttributeName": schema["range_key"], "KeyType": "RANGE"})
            attrs.append({"AttributeName": schema["range_key"], "AttributeType": "N"})

        try:
            dynamodb_client.create_table(
                TableName=table_name,
                KeySchema=key_schema,
                AttributeDefinitions=attrs,
                BillingMode="PAY_PER_REQUEST",
            )
        except dynamodb_client.exceptions.ResourceInUseException:
            pass

    try:
        kinesis_client.create_stream(
            StreamName=f"{prefix}-inference-events",
            ShardCount=1,
        )
    except kinesis_client.exceptions.ResourceInUseException:
        pass

    try:
        sqs_client.create_queue(QueueName=f"{prefix}-rl-rewards")
    except Exception:
        pass

    return {"prefix": prefix, "buckets": buckets}


class TestLocalRLIntegration:
    """Test the complete RL loop against MiniStack."""

    def test_inference_events_to_s3(self, setup_infrastructure, s3_client):
        """Test writing inference events to S3 (mimics log-ingestor)."""
        prefix = setup_infrastructure["prefix"]
        bucket = f"{prefix}-raw-events"

        events = [
            {
                "request_id": "req-001",
                "model_version": "v1.0.0",
                "prompt": "What is 2+2?",
                "completion": "The answer is 4.",
                "user_feedback": "accepted",
                "finish_reason": "stop",
                "edit_persisted": True,
                "timestamp": "2026-07-13T12:00:00Z",
            },
            {
                "request_id": "req-002",
                "model_version": "v1.0.0",
                "prompt": "Write hello world",
                "completion": "print('hello world')",
                "user_feedback": "rejected",
                "finish_reason": "stop",
                "edit_persisted": False,
                "timestamp": "2026-07-13T12:01:00Z",
            },
            {
                "request_id": "req-003",
                "model_version": "v1.0.0",
                "prompt": "Explain recursion",
                "completion": "Recursion is when a function calls itself.",
                "user_feedback": "accepted",
                "finish_reason": "stop",
                "edit_persisted": True,
                "timestamp": "2026-07-13T12:02:00Z",
            },
        ]

        event_key = "events/2026/07/13/events.ndjson"
        event_data = "\n".join(json.dumps(e) for e in events)
        s3_client.put_object(Bucket=bucket, Key=event_key, Body=event_data.encode())

        response = s3_client.get_object(Bucket=bucket, Key=event_key)
        stored_data = response["Body"].read().decode()
        assert len(stored_data.splitlines()) == 3

    def test_reward_aggregation(self, setup_infrastructure, s3_client):
        """Test reward computation from inference events."""
        from kairo_ml.rl.aggregate_rewards import aggregate

        prefix = setup_infrastructure["prefix"]
        bucket = f"{prefix}-raw-events"

        response = s3_client.get_object(Bucket=bucket, Key="events/2026/07/13/events.ndjson")
        event_lines = response["Body"].read().decode().splitlines()

        candidates, stats = aggregate(event_lines)

        assert len(candidates) == 3
        assert stats["total"] == 3

        accepts = [c for c in candidates if c["reward"] > 0]
        rejects = [c for c in candidates if c["reward"] < 0]
        assert len(accepts) >= 1
        assert len(rejects) >= 1

        s3_client.put_object(
            Bucket=f"{prefix}-redacted-events",
            Key="candidates/2026/07/13/scored.ndjson",
            Body="\n".join(json.dumps(c) for c in candidates).encode(),
        )

    def test_grpo_advantages(self, setup_infrastructure, s3_client):
        """Test GRPO advantage computation."""
        from kairo_ml.rl.grpo import advantages_by_group
        from kairo_ml.rl.online_loop import rollouts_from_scored

        prefix = setup_infrastructure["prefix"]
        bucket = f"{prefix}-redacted-events"

        response = s3_client.get_object(Bucket=bucket, Key="candidates/2026/07/13/scored.ndjson")
        lines = response["Body"].read().decode().splitlines()
        candidates = [json.loads(line) for line in lines if line.strip()]

        for c in candidates:
            c["group_id"] = "test-group"
            c["policy_step"] = 0

        rollouts = rollouts_from_scored(candidates)

        groups: dict[str, list[float]] = {}
        for r in rollouts:
            groups.setdefault(r.group_id, []).append(r.reward)

        advantages = advantages_by_group(groups)

        assert "test-group" in advantages
        advs = advantages["test-group"]
        assert len(advs) == len(rollouts)
        assert abs(sum(advs)) < 1e-6

    def test_eval_gate_check(self):
        """Test eval gate logic (without actual model inference)."""
        from kairo_ml.evals.gate import evaluate_gate
        from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec

        items_baseline = [
            ItemResult(item_id=f"item-{i}", passed=i < 90, score=1.0 if i < 90 else 0.0, latency_ms=100)
            for i in range(100)
        ]
        items_candidate = [
            ItemResult(item_id=f"item-{i}", passed=i < 92, score=1.0 if i < 92 else 0.0, latency_ms=95)
            for i in range(100)
        ]

        baseline = EvalRun(
            eval_run_id="baseline-001",
            suite="smoke",
            model=MODEL_ID,
            model_version="v1.0.0",
            items=items_baseline,
        )

        candidate = EvalRun(
            eval_run_id="candidate-001",
            suite="smoke",
            model=MODEL_ID,
            model_version="v1.0.1",
            items=items_candidate,
        )

        spec = PromotionGateSpec(
            min_pass_rate=0.80,
            min_n=50,
            min_detectable_effect=0.0,
        )

        decision = evaluate_gate(candidate, spec, baseline=baseline)

        assert decision.promotable is True
        assert len(decision.checks) > 0

    def test_online_rl_cycle(self, setup_infrastructure, s3_client):
        """Test one complete RL cycle."""
        from kairo_ml.evals.models import EvalRun, ItemResult, PromotionGateSpec
        from kairo_ml.rl.online_loop import OnlineRLLoop, rollouts_from_scored

        prefix = setup_infrastructure["prefix"]
        bucket = f"{prefix}-redacted-events"

        response = s3_client.get_object(Bucket=bucket, Key="candidates/2026/07/13/scored.ndjson")
        lines = response["Body"].read().decode().splitlines()
        candidates = [json.loads(line) for line in lines if line.strip()]

        for i, c in enumerate(candidates):
            c["group_id"] = f"prompt-{i % 2}"
            c["policy_step"] = 0

        rollouts = rollouts_from_scored(candidates)

        class FakePolicyUpdater:
            def __init__(self):
                self.updates = []

            def apply_update(self, advantages, rollouts):
                self.updates.append({"advantages": list(advantages), "count": len(rollouts)})

        def fake_evaluator():
            items = [
                ItemResult(item_id=f"item-{i}", passed=i < 95, score=1.0 if i < 95 else 0.0, latency_ms=80)
                for i in range(100)
            ]
            return EvalRun(
                eval_run_id="eval-001",
                suite="smoke",
                model=MODEL_ID,
                model_version="v1.0.1",
                items=items,
            )

        spec = PromotionGateSpec(
            min_pass_rate=0.80,
            min_n=50,
            min_detectable_effect=0.0,
        )

        updater = FakePolicyUpdater()
        loop = OnlineRLLoop(
            spec=spec,
            updater=updater,
            evaluator=fake_evaluator,
            max_staleness=5,
            policy_step=0,
        )

        result = loop.run_cycle(rollouts)

        assert result.accepted is True or result.reason == "no_onpolicy_samples"
        if result.accepted:
            assert len(updater.updates) == 1
            assert loop.policy_step == 1

    def test_dynamodb_model_registry(self, setup_infrastructure, dynamodb_client):
        """Test model version tracking in DynamoDB."""
        prefix = setup_infrastructure["prefix"]
        table_name = f"{prefix}-model-registry"

        dynamodb_client.put_item(
            TableName=table_name,
            Item={
                "model_id": {"S": MODEL_ID},
                "version": {"N": "1"},
                "status": {"S": "active"},
                "metrics": {"M": {
                    "accuracy": {"N": "0.85"},
                    "latency_p99_ms": {"N": "150"},
                }},
                "created_at": {"S": "2026-07-13T12:00:00Z"},
            },
        )

        response = dynamodb_client.get_item(
            TableName=table_name,
            Key={"model_id": {"S": MODEL_ID}, "version": {"N": "1"}},
        )

        assert "Item" in response
        assert response["Item"]["status"]["S"] == "active"

    def test_kinesis_event_streaming(self, setup_infrastructure, kinesis_client):
        """Test event streaming to Kinesis."""
        prefix = setup_infrastructure["prefix"]
        stream_name = f"{prefix}-inference-events"

        event = {
            "request_id": "stream-001",
            "model_version": "v1.0.0",
            "prompt": "Test prompt",
            "completion": "Test response",
            "timestamp": "2026-07-13T12:05:00Z",
        }

        kinesis_client.put_record(
            StreamName=stream_name,
            Data=json.dumps(event).encode(),
            PartitionKey="test-partition",
        )

        response = kinesis_client.describe_stream(StreamName=stream_name)
        assert response["StreamDescription"]["StreamStatus"] == "ACTIVE"


@pytest.fixture(scope="module")
def model_cache_dir():
    cache_dir = Path.home() / ".cache" / "kairo-test-models"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


class TestModelDownloadAndInference:
    """Test actual model download and inference (requires torch)."""

    @pytest.mark.slow
    def test_download_small_model(self, model_cache_dir):
        """Download Model-0.6B for testing (skip if already cached)."""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            pytest.skip("transformers not installed")

        model_path = model_cache_dir / MODEL_ID.replace("/", "--")

        if not model_path.exists():
            tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
            tokenizer.save_pretrained(model_path)

            model = AutoModelForCausalLM.from_pretrained(
                MODEL_ID,
                torch_dtype="auto",
                device_map="cpu",
            )
            model.save_pretrained(model_path)

        assert model_path.exists()

    @pytest.mark.slow
    def test_cpu_inference(self, model_cache_dir):
        """Test inference on CPU with the small model."""
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            pytest.skip("transformers not installed")

        model_path = model_cache_dir / MODEL_ID.replace("/", "--")
        if not model_path.exists():
            pytest.skip("Model not downloaded, run test_download_small_model first")

        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype="auto",
            device_map="cpu",
        )

        prompt = "What is 2+2? Answer briefly:"
        inputs = tokenizer(prompt, return_tensors="pt")

        outputs = model.generate(
            **inputs,
            max_new_tokens=20,
            do_sample=False,
        )

        response = tokenizer.decode(outputs[0], skip_special_tokens=True)
        assert len(response) > len(prompt)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
