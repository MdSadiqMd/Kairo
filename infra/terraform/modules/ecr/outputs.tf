output "repository_urls" {
  description = "Map of repository URLs keyed by logical name."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "registry_url" {
  description = "The account/region ECR registry host (<acct>.dkr.ecr.<region>.amazonaws.com), derived from a repository URL. Consumed by qctl phase 2 to tag/push images."
  value       = split("/", values(aws_ecr_repository.this)[0].repository_url)[0]
}

output "repository_arns" {
  description = "Map of repository ARNs keyed by logical name."
  value       = { for k, r in aws_ecr_repository.this : k => r.arn }
}

output "repository_names" {
  description = "Map of repository names keyed by logical name."
  value       = { for k, r in aws_ecr_repository.this : k => r.name }
}
