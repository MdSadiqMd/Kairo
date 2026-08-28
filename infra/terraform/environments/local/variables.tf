variable "region" {
  description = "AWS region for the environment (MiniStack ignores this but provider requires it)."
  type        = string
  default     = "us-east-1"
}

variable "aws_endpoint" {
  description = "MiniStack endpoint URL."
  type        = string
  default     = "http://localhost:4566"
}

variable "project" {
  description = "Project tag applied to every resource via default_tags."
  type        = string
  default     = "Kairo"
}

variable "env" {
  description = "Environment tag applied to every resource via default_tags."
  type        = string
  default     = "local"
}

variable "service" {
  description = "Service tag applied to every resource via default_tags."
  type        = string
  default     = "platform"
}

variable "model" {
  description = "Model tag applied to every resource via default_tags."
  type        = string
  default     = "model-0.6b"
}

variable "name_prefix" {
  description = "Prefix for named resources."
  type        = string
  default     = "kairo-cloud-local"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "kairo-cloud-local"
}

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.30.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnets."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "single_nat_gateway" {
  description = "Use a single NAT gateway."
  type        = bool
  default     = true
}

variable "allowed_cidr_blocks" {
  description = "CIDRs allowed to reach the public ALB."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "gpu_instance_families" {
  description = "GPU instance families (unused in local — CPU only)."
  type        = list(string)
  default     = []
}

variable "replicas" {
  description = "Number of CPU vLLM instances to serve."
  type        = number
  default     = 1
}

variable "gpu_instance_type" {
  description = "Instance type for the node pool (CPU in local)."
  type        = string
  default     = "t3.large"
}

variable "tensor_parallel_size" {
  description = "Tensor parallel size (1 for CPU)."
  type        = number
  default     = 1
}

variable "gpus_per_node" {
  description = "GPUs per node (0 for CPU)."
  type        = number
  default     = 0
}

variable "max_total_gpus" {
  description = "NodePool GPU cap (0 for CPU)."
  type        = number
  default     = 0
}

variable "model_id" {
  description = "Hugging Face model id served by vLLM (small model for CPU)."
  type        = string
  default     = "MODEL_PROVIDER/Model-4B"
}

variable "fast_model_id" {
  description = "Hugging Face model id served by the local fast model."
  type        = string
  default     = "MODEL_PROVIDER/Model-1.7B"
}

variable "reasoner_served_model_name" {
  description = "Name served by the reasoner model server."
  type        = string
  default     = "model-32b"
}

variable "fast_served_model_name" {
  description = "Name served by the fast model server."
  type        = string
  default     = "model-8b"
}

variable "reasoner_max_model_len" {
  description = "Local reasoner max model length."
  type        = number
  default     = 4096
}

variable "fast_max_model_len" {
  description = "Local fast max model length."
  type        = number
  default     = 4096
}

variable "max_model_len" {
  description = "Context bound; caps KV-cache."
  type        = number
  default     = 4096
}

variable "log_retention_days" {
  description = "CloudWatch and S3 log retention."
  type        = number
  default     = 7
}

variable "force_destroy_buckets" {
  description = "Allow S3 buckets to be emptied on destroy."
  type        = bool
  default     = true
}

variable "enable_hyperpod" {
  description = "Provision SageMaker HyperPod (disabled in local)."
  type        = bool
  default     = false
}

variable "enable_sagemaker_mlflow" {
  description = "Provision SageMaker MLflow (disabled in local — use container instead)."
  type        = bool
  default     = false
}

variable "enable_guardduty" {
  description = "Enable GuardDuty (disabled in local — no emulation)."
  type        = bool
  default     = false
}

variable "enable_security_hub" {
  description = "Enable Security Hub (disabled in local — no emulation)."
  type        = bool
  default     = false
}

variable "enable_macie" {
  description = "Enable Macie (disabled in local — no emulation)."
  type        = bool
  default     = false
}

variable "enable_cloudtrail" {
  description = "Enable CloudTrail (works in MiniStack)."
  type        = bool
  default     = true
}

variable "enable_secrets_encryption" {
  description = "Envelope-encrypt EKS secrets with a CMK."
  type        = bool
  default     = false
}

variable "eks_endpoint_public_access" {
  description = "Whether the EKS control-plane endpoint is publicly reachable."
  type        = bool
  default     = true
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "opensearch_master_password" {
  description = "OpenSearch fine-grained access control master password."
  type        = string
  sensitive   = true
  default     = "LocalTest123!"
}

variable "opensearch_tls_security_policy" {
  description = "TLS security policy for OpenSearch (MiniStack requires a compatible policy)."
  type        = string
  default     = "Policy-Min-TLS-1-2-2019-07"
}

variable "hf_token_secret_arn" {
  description = "Secrets Manager ARN holding the Hugging Face token."
  type        = string
  default     = ""
}

variable "capacity_reservation_tags" {
  description = "Tag selector for ODCR-backed capacity (unused in local)."
  type        = map(string)
  default     = {}
}

variable "inference_hostname" {
  description = "Optional custom domain for the public inference URL."
  type        = string
  default     = ""
}

variable "enable_fsx" {
  description = "Provision FSx for Lustre (disabled in local — use Docker volumes)."
  type        = bool
  default     = false
}

variable "fsx_storage_capacity_gib" {
  description = "FSx for Lustre capacity in GiB."
  type        = number
  default     = 0
}

variable "require_gpu" {
  description = "Whether GPU is required (false for local CPU mode)."
  type        = bool
  default     = false
}

variable "enable_rl" {
  description = "Enable RL pipeline (unused in local simplified mode)."
  type        = bool
  default     = false
}

variable "force_destroy" {
  description = "Force destroy resources."
  type        = bool
  default     = true
}

variable "zk_inference_enabled" {
  description = "Enable ZK-verifiable inference proofs"
  type        = bool
  default     = true
}
