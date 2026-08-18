from __future__ import annotations

from pathlib import Path
from typing import Protocol

from kairo_common.proofs import ProofReceipt


class ReceiptStore(Protocol):
    def get(self, proof_id: str) -> ProofReceipt | None: ...
    def put(self, receipt: ProofReceipt) -> None: ...
    def update_status(self, proof_id: str, status: str, **fields: str) -> None: ...


class FileReceiptStore:
    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, proof_id: str) -> ProofReceipt | None:
        path = self._dir / f"{proof_id}.json"
        if not path.exists():
            return None
        return ProofReceipt.model_validate_json(path.read_text())

    def put(self, receipt: ProofReceipt) -> None:
        path = self._dir / f"{receipt.proof_id}.json"
        path.write_text(receipt.model_dump_json(indent=2))

    def update_status(self, proof_id: str, status: str, **fields: str) -> None:
        receipt = self.get(proof_id)
        if receipt is None:
            return
        updates: dict = {"status": status, **fields}
        updated = receipt.model_copy(update=updates)
        self.put(updated)


class DynamoReceiptStore:
    def __init__(self, table_name: str) -> None:
        self._table_name = table_name

    def _table(self):
        import boto3

        return boto3.resource("dynamodb").Table(self._table_name)

    def get(self, proof_id: str) -> ProofReceipt | None:
        resp = self._table().get_item(Key={"proof_id": proof_id})
        item = resp.get("Item")
        if not item:
            return None
        return ProofReceipt.model_validate(item)

    def put(self, receipt: ProofReceipt) -> None:
        self._table().put_item(Item=receipt.model_dump())

    def update_status(self, proof_id: str, status: str, **fields: str) -> None:
        expr_parts = ["#s = :s"]
        names = {"#s": "status"}
        values: dict = {":s": status}
        for k, v in fields.items():
            safe = k.replace(".", "_")
            expr_parts.append(f"#{safe} = :{safe}")
            names[f"#{safe}"] = k
            values[f":{safe}"] = v
        self._table().update_item(
            Key={"proof_id": proof_id},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
