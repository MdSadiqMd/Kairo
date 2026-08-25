output "tracking_server_arn" {
  description = "ARN of the MLflow tracking server."
  value       = aws_sagemaker_mlflow_tracking_server.this.arn
}

output "tracking_server_name" {
  description = "Name of the MLflow tracking server."
  value       = aws_sagemaker_mlflow_tracking_server.this.tracking_server_name
}

output "tracking_server_url" {
  description = "URL of the MLflow tracking server."
  value       = aws_sagemaker_mlflow_tracking_server.this.tracking_server_url
}

output "artifact_bucket" {
  description = "Name of the MLflow artifact store bucket."
  value       = aws_s3_bucket.artifacts.bucket
}

output "execution_role_arn" {
  description = "ARN of the SageMaker execution role granting artifact-store access."
  value       = aws_iam_role.execution.arn
}
