output "cluster_name" {
  description = "EKS cluster name for the kubeconfig context."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS control-plane endpoint."
  value       = module.eks.cluster_endpoint
}

output "region" {
  description = "AWS region."
  value       = var.region
}

output "vpc_id" {
  description = "VPC id."
  value       = module.network.vpc_id
}

output "ecr_repository_urls" {
  description = "ECR repository URLs for image pushes."
  value       = module.ecr.repository_urls
}

output "ecr_registry" {
  description = "ECR registry host for `qctl up` image tag/push."
  value       = module.ecr.registry_url
}

output "grafana_url" {
  description = "Grafana URL for the qctl output contract."
  value       = "https://${module.observability.grafana_workspace_endpoint}"
}

output "api_key_secret_arn" {
  description = "Secrets Manager ARN of the router API key (kairo-<env>-api-key)."
  value       = aws_secretsmanager_secret.api_key.arn
}

output "inference_url" {
  description = "Public inference URL; empty until a custom domain is configured."
  value       = var.inference_hostname != "" ? "https://${var.inference_hostname}/v1/chat/completions" : ""
}

output "bucket_names" {
  description = "S3 data-lake bucket names keyed by logical name."
  value       = module.s3_data_lake.bucket_ids
}

output "model_registry_table" {
  description = "DynamoDB model-registry table name (router / promotion service)."
  value       = module.dynamodb.model_registry_table_name
}

output "dynamodb_tables" {
  description = "All DynamoDB table names."
  value       = module.dynamodb.table_names
}

output "kinesis_stream_name" {
  description = "Kinesis inference-events stream name."
  value       = module.eventing.kinesis_stream_name
}

output "grafana_endpoint" {
  description = "Amazon Managed Grafana workspace endpoint."
  value       = module.observability.grafana_workspace_endpoint
}

output "prometheus_endpoint" {
  description = "Amazon Managed Prometheus remote-write / query endpoint."
  value       = module.observability.prometheus_workspace_endpoint
}

output "opensearch_endpoint" {
  description = "Private OpenSearch domain endpoint (hybrid RAG)."
  value       = module.opensearch.domain_endpoint
}

output "aurora_endpoint" {
  description = "Private Aurora PostgreSQL writer endpoint."
  value       = module.aurora.cluster_endpoint
}

output "mlflow_tracking_url" {
  description = "SageMaker managed MLflow tracking server URL."
  value       = module.sagemaker_mlflow.tracking_server_url
}

output "waf_web_acl_arn" {
  description = "WAF WebACL ARN to associate with the ALB during the Kubernetes rollout."
  value       = module.waf.web_acl_arn
}

output "irsa_role_arns" {
  description = "IRSA role ARNs keyed by service (annotate the matching Kubernetes ServiceAccounts)."
  value       = module.iam.role_arns
}

output "fsx_enabled" {
  description = "Whether FSx for Lustre weight staging is provisioned."
  value       = tostring(module.fsx_lustre.enabled)
}

output "fsx_file_system_id" {
  description = "FSx for Lustre filesystem id for the k8s static PV (null when disabled)."
  value       = module.fsx_lustre.file_system_id
}

output "fsx_dns_name" {
  description = "FSx for Lustre DNS name for the CSI static PV (null when disabled)."
  value       = module.fsx_lustre.dns_name
}

output "fsx_mount_name" {
  description = "FSx for Lustre mount name for the CSI static PV (null when disabled)."
  value       = module.fsx_lustre.mount_name
}

output "rl_proofs_queue_url" {
  description = "SQS queue URL for RL proof jobs."
  value       = module.eventing.rl_proofs_queue_url
}

output "proof_receipts_table" {
  description = "DynamoDB proof-receipts table name."
  value       = module.dynamodb.proof_receipts_table_name
}

output "zk_inference_enabled" {
  description = "Whether ZK-verifiable RL proofs are enabled."
  value       = var.zk_inference_enabled
}

output "acm_certificate_arn" {
  description = "ACM certificate ARN for the public ALB listener (empty = HTTP only)."
  value       = var.acm_certificate_arn
}

output "inference_hostname" {
  description = "Custom domain configured for the public inference URL (may be empty)."
  value       = var.inference_hostname
}
