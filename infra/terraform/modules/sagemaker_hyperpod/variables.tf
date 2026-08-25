variable "name_prefix" {
  type        = string
  description = "Prefix applied to the cluster, instance group, IAM role, and Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "enable_hyperpod" {
  type        = bool
  description = "Master switch. When false the module is a no-op and creates nothing."
  default     = false
}

variable "subnet_ids" {
  type        = list(string)
  description = "Private subnet IDs for the cluster VPC config. Empty omits vpc_config."
  default     = []
}

variable "security_group_ids" {
  type        = list(string)
  description = "Security group IDs for the cluster VPC config."
  default     = []
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for the training instance group."
  default     = "ml.p5.48xlarge"
}

variable "instance_count" {
  type        = number
  description = "Number of instances in the training instance group."
  default     = 2
}

variable "lifecycle_config_s3_uri" {
  type        = string
  description = "S3 URI of the cluster lifecycle configuration scripts."
  default     = ""
}

variable "lifecycle_on_create" {
  type        = string
  description = "Name of the on-create lifecycle script within lifecycle_config_s3_uri."
  default     = "on_create.sh"
}

variable "execution_role_arn" {
  type        = string
  description = "Optional existing SageMaker execution role ARN. Empty creates one in-module."
  default     = ""
}

variable "permissions_boundary_arn" {
  type        = string
  description = "Optional IAM permissions boundary ARN applied to the in-module execution role."
  default     = ""
}
