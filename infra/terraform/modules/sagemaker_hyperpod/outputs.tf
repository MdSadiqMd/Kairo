output "cluster_arn" {
  description = "ARN of the HyperPod cluster, or null when disabled."
  value       = one(aws_cloudformation_stack.this[*].outputs["ClusterArn"])
}

output "cluster_name" {
  description = "Name of the HyperPod cluster, or null when disabled."
  value       = local.enabled ? local.cluster_name : null
}

output "enabled" {
  description = "Whether the HyperPod cluster is enabled."
  value       = var.enable_hyperpod
}
