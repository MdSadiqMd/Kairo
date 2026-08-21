"""DynamoDB-backed model registry loader (production).

Only imported when ROUTER_REGISTRY_BACKEND=dynamodb; local/dev and tests use
the file loader and never import boto3. The table holds one item per (role,
name) with the promoted version; deployable is flipped True by the promotion
gate, so the router only ever serves eval-passed versions.
"""

from __future__ import annotations

from typing import Any

from router.model_registry import ModelEntry, RegistryLoader


class DynamoRegistryLoader(RegistryLoader):
    def __init__(self, table_name: str) -> None:
        import boto3  # lazy: keeps boto3 out of the default import path

        self._table = boto3.resource("dynamodb").Table(table_name)

    def load_entries(self) -> list[ModelEntry]:
        entries: list[ModelEntry] = []
        kwargs: dict[str, Any] = {}
        while True:
            resp = self._table.scan(**kwargs)
            for item in resp.get("Items", []):
                if not _is_deployable_registry_item(item):
                    continue
                entries.append(_item_to_entry(item))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return entries


def _is_deployable_registry_item(item: dict[str, Any]) -> bool:
    return all(
        item.get(field)
        for field in ("name", "role", "endpoint", "served_model_id", "max_model_len")
    )


def _item_to_entry(item: dict[str, Any]) -> ModelEntry:
    return ModelEntry(
        name=item["name"],
        role=item["role"],
        version=str(item.get("version", "1")),
        endpoint=item["endpoint"],
        served_model_id=item["served_model_id"],
        max_model_len=int(item["max_model_len"]),
        replicas=int(item.get("replicas", 1)),
        precision=item.get("precision", "fp8"),
        deployable=bool(item.get("deployable", True)),
        policy_version=int(item.get("policy_version", 0)),
    )
