output "region" {
  description = "AWS region."
  value       = var.region
}

output "cluster_name" {
  description = "MiniStack EKS cluster name."
  value       = module.ministack.cluster_name
}

output "cluster_endpoint" {
  description = "MiniStack EKS endpoint."
  value       = module.ministack.cluster_endpoint
}

output "grafana_url" {
  description = "Grafana URL (local observability endpoint)."
  value       = "http://localhost:3000"
}

output "api_key_secret_arn" {
  description = "Secrets Manager ARN of the router API key."
  value       = module.ministack.secret_arns["kairo-${var.env}-api-key"]
}

output "inference_url" {
  description = "Local inference URL via port-forward or NodePort."
  value       = "http://localhost:8080/v1/chat/completions"
}

output "bucket_names" {
  description = "S3 data-lake bucket names."
  value       = module.s3_data_lake.bucket_ids
}

output "model_registry_table" {
  description = "DynamoDB model-registry table name."
  value       = module.ministack.model_registry_table_name
}

output "dynamodb_tables" {
  description = "All DynamoDB table names."
  value       = module.ministack.dynamodb_table_names
}

output "kinesis_stream_name" {
  description = "Kinesis inference-events stream name."
  value       = module.ministack.kinesis_stream_names["inference-events"]
}

output "sqs_queue_urls" {
  description = "SQS queue URLs."
  value       = module.ministack.sqs_queue_urls
}

output "replicas" {
  description = "Number of vLLM replicas."
  value       = var.replicas
}

output "model_id" {
  description = "Model being served."
  value       = var.model_id
}

output "ecr_registry" {
  description = "ECR registry host for local image pushes."
  value       = "host.docker.internal:4566"
}

output "ecr_repository_urls" {
  description = "ECR repository URLs for image pushes."
  value       = module.ministack.ecr_repository_urls
}

output "rl_proofs_queue_url" {
  value = module.ministack.sqs_queue_urls["rl-proofs"]
}

output "proof_receipts_table" {
  description = "DynamoDB proof-receipts table name."
  value       = "kairo-cloud-local-proof-receipts"
}

output "zk_inference_enabled" {
  description = "Whether ZK-verifiable RL proofs are enabled."
  value       = var.zk_inference_enabled
}
