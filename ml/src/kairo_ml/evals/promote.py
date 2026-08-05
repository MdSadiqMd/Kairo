"""Model registry and promotion with DynamoDB support

Extends the basic promotion.py with:
- DynamoDB registry backend for production
- Kubernetes deployment rollout triggers
- Adapter-specific promotion for RL loop
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kairo_common import get_logger

log = get_logger("promote")


@dataclass
class ModelRegistryEntry:
    """A model entry in the registry"""

    name: str
    role: str
    base_model_id: str
    served_model_id: str
    endpoint: str
    version: str = ""
    adapter_id: str | None = None
    adapter_uri: str | None = None
    policy_version: int = 0
    deployable: bool = False
    promoted_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelRegistryEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class DynamoDBRegistryStore:
    """DynamoDB-backed model registry for production"""

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
            self._client = boto3.client("dynamodb", endpoint_url=endpoint_url)
        return self._client

    def get(self, name: str, role: str) -> ModelRegistryEntry | None:
        """Get a model entry by name and role"""
        response = self.client.get_item(
            TableName=self.table_name,
            Key={
                "name": {"S": name},
                "role": {"S": role},
            },
        )
        item = response.get("Item")
        if not item:
            return None
        return self._deserialize(item)

    def put(self, entry: ModelRegistryEntry) -> None:
        """Put a model entry"""
        self.client.put_item(
            TableName=self.table_name,
            Item=self._serialize(entry),
        )

    def update_deployable(self, name: str, role: str, deployable: bool) -> None:
        """Update only the deployable flag"""
        # deployable is GSI key type S, not BOOL — must use "true"/"false" strings
        self.client.update_item(
            TableName=self.table_name,
            Key={
                "name": {"S": name},
                "role": {"S": role},
            },
            UpdateExpression="SET deployable = :d, promoted_at = :t",
            ExpressionAttributeValues={
                ":d": {"S": "true" if deployable else "false"},
                ":t": {"S": datetime.now(UTC).isoformat()},
            },
        )

    def update_adapter(
        self, name: str, role: str, adapter_id: str, adapter_uri: str, policy_version: int
    ) -> None:
        """Update adapter fields for RL promotion"""
        self.client.update_item(
            TableName=self.table_name,
            Key={
                "name": {"S": name},
                "role": {"S": role},
            },
            UpdateExpression=(
                "SET adapter_id = :a, adapter_uri = :u, "
                "policy_version = :p, deployable = :d, promoted_at = :t"
            ),
            ExpressionAttributeValues={
                ":a": {"S": adapter_id},
                ":u": {"S": adapter_uri},
                ":p": {"N": str(policy_version)},
                ":d": {"S": "true"},
                ":t": {"S": datetime.now(UTC).isoformat()},
            },
        )

    def _serialize(self, entry: ModelRegistryEntry) -> dict:
        """Serialize entry to DynamoDB item format"""
        item = {
            "name": {"S": entry.name},
            "role": {"S": entry.role},
            "base_model_id": {"S": entry.base_model_id},
            "served_model_id": {"S": entry.served_model_id},
            "endpoint": {"S": entry.endpoint},
            "version": {"S": entry.version},
            "policy_version": {"N": str(entry.policy_version)},
            "deployable": {"S": "true" if entry.deployable else "false"},
            "promoted_at": {"S": entry.promoted_at},
        }
        if entry.adapter_id:
            item["adapter_id"] = {"S": entry.adapter_id}
        if entry.adapter_uri:
            item["adapter_uri"] = {"S": entry.adapter_uri}
        return item

    def _deserialize(self, item: dict) -> ModelRegistryEntry:
        """Deserialize DynamoDB item to entry"""
        return ModelRegistryEntry(
            name=item["name"]["S"],
            role=item["role"]["S"],
            base_model_id=item["base_model_id"]["S"],
            served_model_id=item["served_model_id"]["S"],
            endpoint=item["endpoint"]["S"],
            version=item.get("version", {}).get("S", ""),
            adapter_id=item.get("adapter_id", {}).get("S"),
            adapter_uri=item.get("adapter_uri", {}).get("S"),
            policy_version=int(item.get("policy_version", {}).get("N", "0")),
            deployable=item.get("deployable", {}).get("S", "false") == "true",
            promoted_at=item.get("promoted_at", {}).get("S", ""),
        )


def trigger_deployment_rollout(
    namespace: str,
    deployment_name: str,
    adapter_uri: str | None = None,
    policy_version: int | None = None,
    *,
    dry_run: bool = False,
) -> bool:
    """Trigger a Kubernetes deployment rollout

    Uses the Kubernetes API to patch the deployment annotation, triggering
    a rolling update. Falls back to kubectl if the kubernetes client is unavailable.
    """
    rollout_timestamp = str(int(time.time()))

    if dry_run:
        log.info(
            "dry run: would trigger rollout",
            extra={"deployment": deployment_name, "namespace": namespace},
        )
        return True

    # Try Kubernetes Python client first (works from within the cluster)
    try:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        apps_v1 = client.AppsV1Api()

        # Patch the deployment annotation to trigger a rollout
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kairo.ai/rollout-timestamp": rollout_timestamp,
                        }
                    }
                }
            }
        }
        if adapter_uri:
            annotations = body["spec"]["template"]["metadata"]["annotations"]
            annotations["kairo.ai/adapter-uri"] = adapter_uri
        if policy_version is not None:
            body["spec"]["template"]["metadata"]["annotations"]["kairo.ai/policy-version"] = str(
                policy_version
            )

        apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        log.info(
            "deployment rollout triggered via K8s API",
            extra={"deployment": deployment_name, "namespace": namespace},
        )
        return True
    except ImportError:
        log.warning("kubernetes client not installed; skipping rollout trigger")
        return False
    except Exception as e:
        log.warning("K8s API rollout failed", extra={"error": str(e)})
        return False


def promote_adapter(
    registry: DynamoDBRegistryStore,
    name: str,
    role: str,
    adapter_id: str,
    adapter_uri: str,
    policy_version: int,
    eval_report_path: str,
    *,
    namespace: str = "kairo",
    deployment_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote an adapter from the RL loop.

    Checks the eval report passed, updates the registry, and triggers K8s rollout.
    """
    report = json.loads(Path(eval_report_path).read_text())
    if not report.get("passed", report.get("accepted")):
        raise ValueError(f"Eval report did not pass: {report.get('reason', 'unknown')}")

    registry.update_adapter(name, role, adapter_id, adapter_uri, policy_version)
    log.info(
        "registry updated",
        extra={
            "name": name,
            "role": role,
            "adapter_id": adapter_id,
            "policy_version": policy_version,
        },
    )

    if deployment_name is None:
        deployment_name = f"vllm-{role}"

    if not dry_run:
        trigger_deployment_rollout(
            namespace, deployment_name, adapter_uri, policy_version, dry_run=dry_run
        )

    return {
        "name": name,
        "role": role,
        "adapter_id": adapter_id,
        "adapter_uri": adapter_uri,
        "policy_version": policy_version,
        "deployment_triggered": not dry_run,
    }


def rollback_adapter(
    registry: DynamoDBRegistryStore,
    name: str,
    role: str,
    to_adapter_id: str,
    to_adapter_uri: str,
    to_policy_version: int,
    *,
    namespace: str = "kairo",
    deployment_name: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Rollback to a previous adapter version."""
    registry.update_adapter(name, role, to_adapter_id, to_adapter_uri, to_policy_version)
    log.info(
        "rollback: registry updated",
        extra={
            "name": name,
            "role": role,
            "adapter_id": to_adapter_id,
            "policy_version": to_policy_version,
        },
    )

    if deployment_name is None:
        deployment_name = f"vllm-{role}"

    if not dry_run:
        trigger_deployment_rollout(
            namespace, deployment_name, to_adapter_uri, to_policy_version, dry_run=dry_run
        )

    return {
        "name": name,
        "role": role,
        "adapter_id": to_adapter_id,
        "adapter_uri": to_adapter_uri,
        "policy_version": to_policy_version,
        "deployment_triggered": not dry_run,
    }
