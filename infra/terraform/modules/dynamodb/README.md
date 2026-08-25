# dynamodb

Metadata tables for the configured model-on-Cloud control plane: model registry, eval-run
metadata, request metadata, and deployment state. All tables use PAY_PER_REQUEST
billing by default, KMS server-side encryption, point-in-time recovery, and
deletion protection.

## Tables

| Logical name | Hash key | Range key | Notes |
|---|---|---|---|
| `model_registry` | `role` (S) | `name` (S) | GSI `deployable-index` on `deployable` (S). |
| `eval_run_metadata` | `eval_run_id` (S) | `model_version` (S) | GSI `model-version-index` on `model_version`. |
| `request_metadata` | `request_id` (S) | `tenant_id` (S) | TTL on `expires_at` (see `enable_ttl`). |
| `deployment_state` | `environment` (S) | `model_role` (S) | Current per-env model deployment. |

DynamoDB is schemaless for non-key attributes, so only key and GSI-key attributes
are declared. The `model_registry` items additionally carry `version`, `endpoint`,
`served_model_id`, `max_model_len`, and `deployable` — these are written by the
application and require no schema declaration. The `deployable-index` GSI lets the
router list deployable models without a full table scan.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `name_prefix` | — | Prefix for all table names. |
| `kms_key_arn` | `""` | CMK for SSE; empty falls back to an AWS-owned key. |
| `billing_mode` | `PAY_PER_REQUEST` | Billing mode. |
| `deletion_protection` | `true` | Deletion protection on all tables. |
| `enable_ttl` | `true` | Toggle TTL on `request_metadata`. |

## Key outputs

- `table_names` / `table_arns` — maps keyed by the logical names above.
- `model_registry_table_name`, `model_registry_table_arn`,
  `eval_run_metadata_table_arn`, `request_metadata_table_arn`,
  `deployment_state_table_arn` — individual references for IAM policies.
