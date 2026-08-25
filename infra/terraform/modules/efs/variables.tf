variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "enable_efs" {
  description = "Whether to create the EFS file system"
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "VPC ID for security group"
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR for NFS ingress rule"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for mount targets"
  type        = list(string)
}

variable "kms_key_arn" {
  description = "KMS key ARN for encryption at rest"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
