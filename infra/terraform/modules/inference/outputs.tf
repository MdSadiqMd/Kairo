output "total_gpus" {
  description = "replicas * tensor_parallel_size — total GPUs the deployment requests."
  value       = local.total_gpus
}

output "nodes" {
  description = "ceil(total_gpus / gpus_per_node) — number of gpu_instance_type nodes Karpenter provisions."
  value       = local.nodes
}

output "nodepool_yaml" {
  description = "Rendered Karpenter EC2NodeClass + NodePool (single instance type) YAML for kubectl apply."
  value       = local.nodepool_yaml
}

output "deployment_yaml" {
  description = "Rendered vLLM Deployment YAML (replicas = replicas, request == limit GPUs)."
  value       = local.deployment_yaml
}

output "instance_type" {
  description = "The single GPU instance type the NodePool may launch."
  value       = var.gpu_instance_type
}

output "model_id" {
  description = "Hugging Face model id served."
  value       = var.model_id
}

output "nodepool_name" {
  description = "Name of the Karpenter NodePool."
  value       = local.nodepool_name
}

output "deployment_name" {
  description = "Name of the vLLM Deployment."
  value       = local.app_name
}
