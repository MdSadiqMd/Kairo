output "s3_key_arn" {
  description = "ARN of the S3 data-lake CMK."
  value       = aws_kms_key.s3.arn
}

output "s3_key_id" {
  description = "Key ID of the S3 data-lake CMK."
  value       = aws_kms_key.s3.key_id
}

output "ebs_key_arn" {
  description = "ARN of the EBS CMK."
  value       = aws_kms_key.ebs.arn
}

output "ebs_key_id" {
  description = "Key ID of the EBS CMK."
  value       = aws_kms_key.ebs.key_id
}

output "cloudwatch_key_arn" {
  description = "ARN of the CloudWatch Logs CMK."
  value       = aws_kms_key.cloudwatch.arn
}

output "cloudwatch_key_id" {
  description = "Key ID of the CloudWatch Logs CMK."
  value       = aws_kms_key.cloudwatch.key_id
}

output "dynamodb_key_arn" {
  description = "ARN of the DynamoDB CMK."
  value       = aws_kms_key.dynamodb.arn
}

output "dynamodb_key_id" {
  description = "Key ID of the DynamoDB CMK."
  value       = aws_kms_key.dynamodb.key_id
}

output "opensearch_key_arn" {
  description = "ARN of the OpenSearch CMK."
  value       = aws_kms_key.opensearch.arn
}

output "opensearch_key_id" {
  description = "Key ID of the OpenSearch CMK."
  value       = aws_kms_key.opensearch.key_id
}

output "key_arns" {
  description = "Map of all CMK ARNs keyed by logical purpose."
  value = {
    s3         = aws_kms_key.s3.arn
    ebs        = aws_kms_key.ebs.arn
    cloudwatch = aws_kms_key.cloudwatch.arn
    dynamodb   = aws_kms_key.dynamodb.arn
    opensearch = aws_kms_key.opensearch.arn
  }
}
