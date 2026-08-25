output "table_names" {
  description = "Map of logical name to DynamoDB table name."
  value = {
    model_registry    = aws_dynamodb_table.model_registry.name
    eval_run_metadata = aws_dynamodb_table.eval_run_metadata.name
    request_metadata  = aws_dynamodb_table.request_metadata.name
    deployment_state  = aws_dynamodb_table.deployment_state.name
    proof_receipts    = aws_dynamodb_table.proof_receipts.name
  }
}

output "table_arns" {
  description = "Map of logical name to DynamoDB table ARN."
  value = {
    model_registry    = aws_dynamodb_table.model_registry.arn
    eval_run_metadata = aws_dynamodb_table.eval_run_metadata.arn
    request_metadata  = aws_dynamodb_table.request_metadata.arn
    deployment_state  = aws_dynamodb_table.deployment_state.arn
    proof_receipts    = aws_dynamodb_table.proof_receipts.arn
  }
}

output "model_registry_table_arn" {
  description = "ARN of the model-registry table."
  value       = aws_dynamodb_table.model_registry.arn
}

output "model_registry_table_name" {
  description = "Name of the model-registry table."
  value       = aws_dynamodb_table.model_registry.name
}

output "eval_run_metadata_table_arn" {
  description = "ARN of the eval-run-metadata table."
  value       = aws_dynamodb_table.eval_run_metadata.arn
}

output "request_metadata_table_arn" {
  description = "ARN of the request-metadata table."
  value       = aws_dynamodb_table.request_metadata.arn
}

output "deployment_state_table_arn" {
  description = "ARN of the deployment-state table."
  value       = aws_dynamodb_table.deployment_state.arn
}

output "proof_receipts_table_name" {
  description = "Name of the proof-receipts table."
  value       = aws_dynamodb_table.proof_receipts.name
}

output "proof_receipts_table_arn" {
  description = "ARN of the proof-receipts table."
  value       = aws_dynamodb_table.proof_receipts.arn
}
