from decimal import Decimal

from router.registry_dynamodb import _is_deployable_registry_item, _item_to_entry


def test_item_to_entry_normalizes_dynamodb_numbers() -> None:
    entry = _item_to_entry(
        {
            "name": "reasoner",
            "role": "reasoner",
            "version": Decimal("1"),
            "endpoint": "http://vllm-reasoner:8000",
            "served_model_id": "reasoner",
            "max_model_len": Decimal("2048"),
            "replicas": Decimal("1"),
            "precision": "fp32",
            "deployable": True,
            "policy_version": Decimal("0"),
        }
    )

    assert entry.version == "1"
    assert entry.max_model_len == 2048
    assert entry.replicas == 1


def test_incomplete_registry_rows_are_not_deployable() -> None:
    assert not _is_deployable_registry_item({"name": "reasoner", "role": "reasoner"})
