# security_baseline

Account-level security services for the training-data perimeter (§9.2, §19.5):
GuardDuty, Security Hub, CloudTrail, and Macie.

## What it creates

- **GuardDuty** (`enable_guardduty`): a detector plus feature toggles for
  `S3_DATA_EVENTS`, `EKS_AUDIT_LOGS`, `EKS_RUNTIME_MONITORING`, and
  `RUNTIME_MONITORING` — the S3 Protection and EKS Runtime Monitoring called for
  in §19.5.
- **Security Hub** (`enable_security_hub`): the account subscription with the AWS
  Foundational Security Best Practices and CIS AWS Foundations standards.
- **CloudTrail** (`enable_cloudtrail`): a multi-region trail with log file
  validation and optional KMS encryption. It records management events (read +
  write) **and** S3 object-level data events scoped to
  `training_data_bucket_arns`.
- **Macie** (`enable_macie`): account enablement for continuous S3 scans.

## Why CloudTrail data events on training buckets

§19.5 ("S3 hard controls") mandates **CloudTrail data events on training-data
buckets** as part of the data perimeter: management events alone do not capture
object `GetObject`/`PutObject` activity. Scoping an advanced event selector to
the training-data bucket ARNs makes every read and write of training data
auditable — the evidence trail that detects credential misuse trying to exfiltrate
the corpus — without paying for data events on every bucket in the account.

## CloudTrail bucket

If `cloudtrail_bucket_name` is empty, the module creates
`<name_prefix>-cloudtrail-<account>` with versioning, full Block Public Access,
KMS/SSE encryption, and a bucket policy granting only the `cloudtrail.amazonaws.com`
service principal (with `aws:SourceArn` conditions) plus a TLS-only deny.

## Outputs

`guardduty_detector_id`, `securityhub_account_id`, `cloudtrail_arn`,
`cloudtrail_name`, `macie_account_id`, `cloudtrail_bucket_name`.
