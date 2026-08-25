output "domain_name" {
  description = "OpenSearch domain name."
  value       = aws_opensearch_domain.this.domain_name
}

output "domain_arn" {
  description = "OpenSearch domain ARN."
  value       = aws_opensearch_domain.this.arn
}

output "domain_endpoint" {
  description = "VPC endpoint for the domain (search/index API)."
  value       = aws_opensearch_domain.this.endpoint
}

output "domain_id" {
  description = "OpenSearch domain ID."
  value       = aws_opensearch_domain.this.domain_id
}

output "security_group_id" {
  description = "Security group ID controlling access to the domain."
  value       = aws_security_group.this.id
}

output "kibana_endpoint" {
  description = "OpenSearch Dashboards endpoint."
  value       = aws_opensearch_domain.this.dashboard_endpoint
}

output "dashboard_endpoint" {
  description = "Alias of kibana_endpoint (OpenSearch Dashboards)."
  value       = aws_opensearch_domain.this.dashboard_endpoint
}
