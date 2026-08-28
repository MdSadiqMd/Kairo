output "guardduty_detector_id" {
  description = "ID of the GuardDuty detector, or null when disabled."
  value       = one(aws_guardduty_detector.this[*].id)
}

output "securityhub_account_id" {
  description = "ID of the Security Hub account subscription, or null when disabled."
  value       = one(aws_securityhub_account.this[*].id)
}

output "cloudtrail_arn" {
  description = "ARN of the CloudTrail trail, or null when disabled."
  value       = one(aws_cloudtrail.this[*].arn)
}

output "cloudtrail_name" {
  description = "Name of the CloudTrail trail, or null when disabled."
  value       = one(aws_cloudtrail.this[*].name)
}

output "macie_account_id" {
  description = "ID of the Macie account, or null when disabled."
  value       = one(aws_macie2_account.this[*].id)
}

output "cloudtrail_bucket_name" {
  description = "Name of the S3 bucket receiving CloudTrail logs (provided or in-module)."
  value       = local.trail_bucket_name
}
