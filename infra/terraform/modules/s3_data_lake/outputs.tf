output "bucket_ids" {
  description = "Map of bucket names keyed by logical name."
  value       = { for k, b in aws_s3_bucket.this : k => b.id }
}

output "bucket_arns" {
  description = "Map of bucket ARNs keyed by logical name."
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}

output "raw_events_bucket" {
  description = "Name of the raw-events bucket."
  value       = aws_s3_bucket.this["raw_events"].id
}

output "redacted_events_bucket" {
  description = "Name of the redacted-events bucket."
  value       = aws_s3_bucket.this["redacted_events"].id
}

output "datasets_bucket" {
  description = "Name of the datasets bucket."
  value       = aws_s3_bucket.this["datasets"].id
}

output "model_artifacts_bucket" {
  description = "Name of the model-artifacts bucket."
  value       = aws_s3_bucket.this["model_artifacts"].id
}

output "checkpoints_bucket" {
  description = "Name of the checkpoints bucket."
  value       = aws_s3_bucket.this["checkpoints"].id
}

output "eval_results_bucket" {
  description = "Name of the eval-results bucket."
  value       = aws_s3_bucket.this["eval_results"].id
}

output "audit_logs_bucket" {
  description = "Name of the audit-logs bucket."
  value       = aws_s3_bucket.this["audit_logs"].id
}
