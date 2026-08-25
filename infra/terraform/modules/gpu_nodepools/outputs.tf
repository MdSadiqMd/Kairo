output "nodepool_manifests" {
  description = "Map of pool name to rendered Karpenter NodePool YAML (karpenter.sh/v1)."
  value       = local.nodepool_manifests
}

output "ec2nodeclass_manifests" {
  description = "Map of pool name to rendered Karpenter EC2NodeClass YAML (karpenter.k8s.aws/v1)."
  value       = local.ec2nodeclass_manifests
}

output "all_manifests_yaml" {
  description = "All EC2NodeClass and NodePool documents joined into a single multi-doc YAML stream for kubectl apply."
  value       = join("\n---\n", local.all_manifests)
}
