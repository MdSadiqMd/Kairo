variable "name_prefix" {
  type        = string
  description = "Prefix applied to rendered resource names and instance tags."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags merged onto EC2NodeClass instance tags."
}

variable "discovery_tag" {
  type        = string
  default     = ""
  description = "Value of the karpenter.sh/discovery tag used to select subnets and security groups. Defaults to name_prefix when empty."
}

variable "karpenter_node_role_name" {
  type        = string
  description = "IAM role name assumed by Karpenter nodes (from the karpenter module)."
}

variable "ami_family" {
  type        = string
  default     = "AL2023"
  description = "AMI family for the EC2NodeClass alias (e.g. AL2023 -> al2023@latest)."
}

variable "cluster_name" {
  type        = string
  description = "EKS cluster name the NodePools target."
}

variable "capacity_reservation_tags" {
  type        = map(string)
  default     = {}
  description = "Tags selecting On-Demand Capacity Reservations for the gpu-inference-large pool."
}

variable "root_volume_size" {
  type        = string
  default     = "200Gi"
  description = "gp3 root volume size for node instances."
}

variable "cpu_arch" {
  type        = list(string)
  default     = ["amd64", "arm64"]
  description = "Allowed CPU architectures for the cpu-system pool."
}

variable "expire_after" {
  type        = string
  default     = "168h"
  description = "Node expiry for inference, batch, and system pools (7 days)."
}

variable "expire_after_training" {
  type        = string
  default     = "720h"
  description = "Longer node expiry for the training pool (30 days)."
}

variable "gpu_inference_small_limit" {
  type        = number
  default     = 32
  description = "Max nvidia.com/gpu for the gpu-inference-small pool."
}

variable "gpu_inference_large_limit" {
  type        = number
  default     = 64
  description = "Max nvidia.com/gpu for the gpu-inference-large pool."
}

variable "gpu_batch_eval_limit" {
  type        = number
  default     = 32
  description = "Max nvidia.com/gpu for the gpu-batch-eval pool."
}

variable "gpu_training_limit" {
  type        = number
  default     = 64
  description = "Max nvidia.com/gpu for the gpu-training pool."
}

variable "cpu_system_cpu_limit" {
  type        = number
  default     = 1000
  description = "Max aggregate vCPU for the cpu-system pool."
}
