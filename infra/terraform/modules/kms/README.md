# kms

Customer-managed KMS keys (CMKs) for the platform, one per data domain: S3,
EBS, CloudWatch Logs, DynamoDB, and OpenSearch. Every key has rotation enabled
and a configurable deletion window.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `name_prefix` | — | Prefix for aliases (`alias/<prefix>-<domain>`) and Name tags. |
| `deletion_window_days` | `30` | Pending-deletion waiting period (7–30). |
| `tags` | `{}` | Extra tags merged onto each key. |

## Key outputs

`s3_key_arn` / `s3_key_id`, `ebs_key_arn` / `ebs_key_id`,
`cloudwatch_key_arn` / `cloudwatch_key_id`, `dynamodb_key_arn` / `dynamodb_key_id`,
`opensearch_key_arn` / `opensearch_key_id`, and `key_arns` — a `map(string)` of
all five ARNs keyed by `s3` / `ebs` / `cloudwatch` / `dynamodb` / `opensearch`.

## Design notes

- Every key policy grants the account root full `kms:*` admin, then adds a
  narrowly scoped usage statement for the consuming service.
- The **cloudwatch** key restricts the `logs.<region>.amazonaws.com` principal
  to log groups in this account/region via the `kms:EncryptionContext:aws:logs:arn`
  condition rather than a blanket allow.
- The **opensearch** key allows the `es.amazonaws.com` service principal.
- The **s3**, **ebs**, and **dynamodb** keys restrict usage to their service via
  `kms:ViaService` plus a `kms:CallerAccount` condition, so only in-account
  principals acting through that service can use the key.
- No account IDs are hardcoded — they resolve from `aws_caller_identity`.
