variable "name_prefix" {
  description = "Prefix for all named resources and Karpenter discovery, e.g. kairo-cloud-dev."
  type        = string
}

variable "tags" {
  description = "Additional tags merged onto taggable resources. Common project/env tags come from provider default_tags."
  type        = map(string)
  default     = {}
}

variable "gpu_instance_type" {
  description = "The single GPU instance type the NodePool may launch (one-type constraint)."
  type        = string
  default     = "g5.12xlarge"
}

variable "gpus_per_node" {
  description = "GPUs physically present on gpu_instance_type. g5.12xlarge = 4x A10G."
  type        = number
  default     = 4
}

variable "tensor_parallel_size" {
  description = "GPUs each configured model instance shards across (vLLM --tensor-parallel-size). Must divide 64 attn heads and 8 KV heads."
  type        = number
  default     = 4

  validation {
    condition     = contains([1, 2, 4, 8], var.tensor_parallel_size)
    error_message = "tensor_parallel_size must be one of [1, 2, 4, 8] so it divides Model-32B's 64 attention heads and 8 KV heads."
  }
}

variable "replicas" {
  description = "THE control knob: how many configured model instances to run. Kubernetes schedules this many tensor_parallel_size-GPU pods."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 0
    error_message = "replicas must be zero or positive."
  }
}

variable "max_total_gpus" {
  description = "NodePool GPU cap (limits.nvidia.com/gpu) that bounds the fleet so a large replica count cannot run away on cost."
  type        = number
  default     = 16
}

variable "model_id" {
  description = "Hugging Face model id served by vLLM."
  type        = string
  default     = "MODEL_PROVIDER/Model-32B"
}

variable "max_model_len" {
  description = "Context bound; caps KV-cache VRAM per sequence."
  type        = number
  default     = 16384
}

variable "discovery_tag" {
  description = "Value of the karpenter.sh/discovery tag on subnets and security groups. Defaults to name_prefix."
  type        = string
  default     = ""
}

variable "karpenter_node_role_name" {
  description = "IAM role name Karpenter assigns to launched nodes (from the karpenter module)."
  type        = string
}

variable "ami_family" {
  description = "Karpenter EC2NodeClass AMI family / alias source."
  type        = string
  default     = "AL2023"
}

variable "root_volume_size_gib" {
  description = "gp3 root volume size in GiB. ~300 GiB holds the ~64 GB Model-32B weight download plus headroom."
  type        = number
  default     = 300
}

variable "root_volume_throughput" {
  description = "gp3 provisioned throughput (MB/s). gp3 decouples throughput from size for ~1 GB/s weight loads."
  type        = number
  default     = 1000
}

variable "root_volume_iops" {
  description = "gp3 provisioned IOPS."
  type        = number
  default     = 4000
}

variable "dev_shm_size" {
  description = "Size of the in-memory /dev/shm emptyDir. Must be >=16Gi for NCCL over shared memory or multi-GPU startup hangs."
  type        = string
  default     = "16Gi"
}

variable "namespace" {
  description = "Kubernetes namespace for the vLLM Deployment."
  type        = string
  default     = "kairo"
}

variable "vllm_image" {
  description = "Container image for the vLLM server (ECR repo populated by the image build step)."
  type        = string
  default     = "vllm/vllm-openai:latest"
}

variable "model_artifacts_bucket" {
  description = "Optional S3 bucket name for staging model weights; empty means pull from Hugging Face on cold start."
  type        = string
  default     = ""
}

variable "gpu_taint_key" {
  description = "Taint key isolating GPU nodes; inference pods tolerate it and request nvidia.com/gpu."
  type        = string
  default     = "nvidia.com/gpu"
}

variable "require_gpu" {
  description = "Whether GPU is required. When false (local/CPU mode), GPU preconditions are relaxed."
  type        = bool
  default     = true
}
