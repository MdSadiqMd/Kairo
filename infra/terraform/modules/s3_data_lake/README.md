# s3_data_lake

The platform's S3 data lake: `raw-events`, `redacted-events`, `datasets`,
`model-artifacts`, `checkpoints`, `eval-results`, and `audit-logs`. All buckets
are built from a single `for_each` over a per-bucket config map.

## Per-bucket behavior

| Logical name | Versioning | Object Lock | Intelligent-Tiering | Lifecycle |
|---|---|---|---|---|
| raw_events | — | — | yes | expire @ `log_retention_days` |
| redacted_events | — | — | — | — |
| datasets | yes | — | — | — |
| model_artifacts | yes | — | — | — |
| checkpoints | — | — | — | transition IA @30d, Glacier @90d |
| eval_results | — | — | — | — |
| audit_logs | yes | yes | — | — |

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `s3_kms_key_arn` | — | CMK for SSE-KMS on every bucket. |
| `force_destroy` | `false` | Allow deletion of non-empty buckets. |
| `log_retention_days` | `30` | Raw-events expiration. |
| `object_lock_mode` | `GOVERNANCE` | Audit-logs lock mode (or `COMPLIANCE`). |
| `audit_log_retention_years` | `7` | Audit-logs lock retention. |
| `manage_account_public_access_block` | `true` | Manage account-level BPA. |

## Key outputs

`bucket_ids` and `bucket_arns` (maps keyed by logical name), plus per-bucket
name outputs `raw_events_bucket`, `redacted_events_bucket`, `datasets_bucket`,
`model_artifacts_bucket`, `checkpoints_bucket`, `eval_results_bucket`,
`audit_logs_bucket`.

## Design notes

- Every bucket enforces SSE-KMS (`bucket_key_enabled = true`), full public
  access block, and a bucket policy that denies non-TLS access and denies any
  `PutObject` that is not `aws:kms`-encrypted.
- Object Lock requires `object_lock_enabled = true` at bucket creation, so it is
  set on the `audit-logs` bucket up front and paired with versioning.
- Server access logs from every other bucket land in `audit-logs`; the audit
  bucket is not logged into itself.
- An account-level Block Public Access is emitted when
  `manage_account_public_access_block` is true — set it false if the account
  baseline is owned elsewhere to avoid ownership conflicts.
