output "bucket_ids" {
  description = "Map of bucket logical names to their IDs."
  value       = { for k, v in aws_s3_bucket.data_lake : trimprefix(k, "${var.name_prefix}-") => v.id }
}

output "bucket_arns" {
  description = "Map of bucket logical names to their ARNs."
  value       = { for k, v in aws_s3_bucket.data_lake : trimprefix(k, "${var.name_prefix}-") => v.arn }
}

output "dynamodb_table_names" {
  description = "Map of table logical names to their names."
  value       = { for k, v in aws_dynamodb_table.tables : k => v.name }
}

output "dynamodb_table_arns" {
  description = "Map of table logical names to their ARNs."
  value       = { for k, v in aws_dynamodb_table.tables : k => v.arn }
}

output "kinesis_stream_names" {
  description = "Map of stream logical names to their names."
  value       = { for k, v in aws_kinesis_stream.streams : k => v.name }
}

output "kinesis_stream_arns" {
  description = "Map of stream logical names to their ARNs."
  value       = { for k, v in aws_kinesis_stream.streams : k => v.arn }
}

output "sqs_queue_urls" {
  description = "Map of queue logical names to their URLs."
  value       = { for k, v in aws_sqs_queue.queues : k => v.url }
}

output "sqs_queue_arns" {
  description = "Map of queue logical names to their ARNs."
  value       = { for k, v in aws_sqs_queue.queues : k => v.arn }
}

output "secret_arns" {
  description = "Map of secret names to their ARNs."
  value       = { for k, v in aws_secretsmanager_secret.secrets : k => v.arn }
}

output "model_registry_table_name" {
  description = "Name of the model registry DynamoDB table."
  value       = aws_dynamodb_table.tables["model-registry"].name
}

output "model_registry_table_arn" {
  description = "ARN of the model registry DynamoDB table."
  value       = aws_dynamodb_table.tables["model-registry"].arn
}

output "cluster_name" {
  description = "MiniStack EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "MiniStack EKS endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "ecr_repository_urls" {
  description = "Repository URLs keyed by service image name."
  value       = { for k, v in aws_ecr_repository.repositories : k => v.repository_url }
}

output "ecr_registry_url" {
  description = "Registry host used by qctl image build/push."
  value       = replace(aws_ecr_repository.repositories["router"].repository_url, "/kairo/router", "")
}
