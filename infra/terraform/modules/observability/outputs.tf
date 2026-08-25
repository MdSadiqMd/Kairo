output "prometheus_workspace_id" {
  description = "Amazon Managed Prometheus workspace ID."
  value       = aws_prometheus_workspace.this.id
}

output "prometheus_workspace_arn" {
  description = "Amazon Managed Prometheus workspace ARN."
  value       = aws_prometheus_workspace.this.arn
}

output "prometheus_workspace_endpoint" {
  description = "Amazon Managed Prometheus remote-write/query endpoint."
  value       = aws_prometheus_workspace.this.prometheus_endpoint
}

output "prometheus_endpoint" {
  description = "Alias of prometheus_workspace_endpoint."
  value       = aws_prometheus_workspace.this.prometheus_endpoint
}

output "grafana_workspace_id" {
  description = "Amazon Managed Grafana workspace ID."
  value       = aws_grafana_workspace.this.id
}

output "grafana_workspace_endpoint" {
  description = "Amazon Managed Grafana workspace endpoint (URL host)."
  value       = aws_grafana_workspace.this.endpoint
}

output "grafana_workspace_arn" {
  description = "Amazon Managed Grafana workspace ARN."
  value       = aws_grafana_workspace.this.arn
}

output "log_group_names" {
  description = "Map of component to CloudWatch log group name."
  value       = { for c, lg in aws_cloudwatch_log_group.this : c => lg.name }
}

output "log_group_arns" {
  description = "Map of component to CloudWatch log group ARN."
  value       = { for c, lg in aws_cloudwatch_log_group.this : c => lg.arn }
}
