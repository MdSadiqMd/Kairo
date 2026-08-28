variable "region" {
  description = "AWS region for the environment."
  type        = string
  default     = "us-west-2"
}

variable "project" {
  description = "Project tag applied to every resource via default_tags."
  type        = string
  default     = "Kairo"
}

variable "env" {
  description = "Environment tag applied to every resource via default_tags."
  type        = string
  default     = "prod"
}

variable "service" {
  description = "Service tag applied to every resource via default_tags."
  type        = string
  default     = "platform"
}

variable "model" {
  description = "Model tag applied to every resource via default_tags."
  type        = string
  default     = "model-32b"
}

variable "name_prefix" {
  description = "Prefix for named resources and Karpenter discovery tag."
  type        = string
  default     = "kairo-cloud-prod"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "kairo-cloud-prod"
}

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.30.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnets (three for prod)."
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b", "us-west-2c"]
}

variable "single_nat_gateway" {
  description = "Use a single NAT gateway. Prod uses one per AZ for fault isolation."
  type        = bool
  default     = false
}

variable "allowed_cidr_blocks" {
  description = "CIDRs allowed to reach the public ALB (company VPN / office IPs)."
  type        = list(string)
  default     = []
}

variable "gpu_instance_families" {
  description = "GPU instance families available to the Karpenter NodePools."
  type        = list(string)
  default     = ["g5", "g6", "g6e", "p5"]
}

variable "replicas" {
  description = "The one knob: how many Model-32B instances to serve."
  type        = number
  default     = 2
}

variable "gpu_instance_type" {
  description = "Single GPU instance type for the configured model NodePool."
  type        = string
  default     = "g5.12xlarge"
}

variable "tensor_parallel_size" {
  description = "GPUs each configured model instance shards across."
  type        = number
  default     = 4
}

variable "gpus_per_node" {
  description = "GPUs per gpu_instance_type node."
  type        = number
  default     = 4
}

variable "max_total_gpus" {
  description = "NodePool GPU cap for cost safety."
  type        = number
  default     = 64
}

variable "model_id" {
  description = "Hugging Face model id served by vLLM."
  type        = string
  default     = "MODEL_PROVIDER/Model-32B"
}

variable "max_model_len" {
  description = "Context bound; caps KV-cache VRAM."
  type        = number
  default     = 16384
}

variable "log_retention_days" {
  description = "CloudWatch and S3 log retention (365 for prod)."
  type        = number
  default     = 365
}

variable "force_destroy_buckets" {
  description = "Allow S3 buckets to be emptied on destroy. Never in prod."
  type        = bool
  default     = false
}

variable "enable_hyperpod" {
  description = "Provision the optional SageMaker HyperPod cluster."
  type        = bool
  default     = false
}

variable "enable_secrets_encryption" {
  description = "Envelope-encrypt EKS secrets with a CMK."
  type        = bool
  default     = true
}

variable "eks_endpoint_public_access" {
  description = "Whether the EKS control-plane endpoint is publicly reachable."
  type        = bool
  default     = false
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint."
  type        = list(string)
  default     = []
}

variable "opensearch_master_password" {
  description = "OpenSearch fine-grained access control master password. Supply via TF_VAR_opensearch_master_password."
  type        = string
  sensitive   = true
  default     = ""
}

variable "hf_token_secret_arn" {
  description = "Secrets Manager ARN holding the Hugging Face token for weight downloads."
  type        = string
  default     = ""
}

variable "capacity_reservation_tags" {
  description = "Tag selector for ODCR-backed capacity used by the large-inference NodePool."
  type        = map(string)
  default = {
    "kairo:capacity-type" = "odcr"
  }
}

variable "inference_hostname" {
  description = "Custom domain for the public inference URL (e.g. api.kairo.example.com)."
  type        = string
  default     = ""
}

variable "enable_fsx" {
  description = "Provision FSx for Lustre weight staging. On in prod."
  type        = bool
  default     = true
}

variable "enable_efs" {
  description = "Provision EFS for adapter storage (RL candidate adapters, RWX)."
  type        = bool
  default     = true
}

variable "fsx_storage_capacity_gib" {
  description = "FSx for Lustre capacity in GiB (PERSISTENT_2 increments of 1200)."
  type        = number
  default     = 2400
}

variable "zk_inference_enabled" {
  description = "Enable ZK-verifiable RL proofs. Single toggle for proof queue, worker, and witness capture."
  type        = bool
  default     = true
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the public ALB HTTPS listener. Empty serves HTTP only (dev/test)."
  type        = string
  default     = ""
}
