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
  default     = "dev"
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
  default     = "kairo-cloud-dev"
}

variable "cluster_name" {
  description = "EKS cluster name."
  type        = string
  default     = "kairo-cloud-dev"
}

variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.20.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for subnets (three for prod parity)."
  type        = list(string)
  default     = ["us-west-2a", "us-west-2b", "us-west-2c"]
}

variable "single_nat_gateway" {
  description = "Use a single NAT gateway (dev cost saving). Prod uses one per AZ."
  type        = bool
  default     = true
}

variable "allowed_cidr_blocks" {
  description = "CIDRs allowed to reach the public ALB (company VPN / office IPs)."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "gpu_instance_families" {
  description = "GPU instance families available to the Karpenter NodePools."
  type        = list(string)
  default     = ["g5", "g6", "g6e", "p5"]
}

variable "replicas" {
  description = "The one knob: how many Model-32B instances to serve."
  type        = number
  default     = 1
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
  default     = 16
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
  description = "CloudWatch and S3 log retention (30 dev, 365 prod)."
  type        = number
  default     = 30
}

variable "force_destroy_buckets" {
  description = "Allow S3 buckets to be emptied on destroy. Dev only; never in prod."
  type        = bool
  default     = true
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
  default     = true
}

variable "eks_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint."
  type        = list(string)
  default     = ["0.0.0.0/0"]
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
  default     = {}
}

variable "inference_hostname" {
  description = "Optional custom domain for the public inference URL (e.g. api.kairo.example.com). Empty in dev, where the ALB DNS is used directly."
  type        = string
  default     = ""
}

variable "enable_fsx" {
  description = "Provision FSx for Lustre weight staging. Off in dev by default."
  type        = bool
  default     = false
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
