variable "name_prefix" {
  description = "Prefix for the cluster, subnet group, and security group names."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "VPC ID hosting the cluster security group."
  type        = string
}

variable "subnet_ids" {
  description = "Private-data subnet IDs for the DB subnet group."
  type        = list(string)
}

variable "vpc_cidr" {
  description = "VPC CIDR allowed to reach the cluster on 5432."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key ARN for storage encryption and the managed master-user secret."
  type        = string
}

variable "database_name" {
  description = "Initial database name."
  type        = string
  default     = "kairo"
}

variable "master_username" {
  description = "Master username. The password is managed by Secrets Manager."
  type        = string
  default     = "kairo_admin"
}

variable "min_capacity" {
  description = "Serverless v2 minimum ACU."
  type        = number
  default     = 0.5
}

variable "max_capacity" {
  description = "Serverless v2 maximum ACU."
  type        = number
  default     = 4
}

variable "engine_version" {
  description = "Aurora PostgreSQL engine version."
  type        = string
  default     = "16.4"
}

variable "backup_retention_period" {
  description = "Automated backup retention in days."
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Enable deletion protection on the cluster."
  type        = bool
  default     = true
}

variable "skip_final_snapshot" {
  description = "Skip the final snapshot on cluster deletion."
  type        = bool
  default     = false
}

variable "instance_count" {
  description = "Number of Serverless v2 cluster instances (>= 1)."
  type        = number
  default     = 1

  validation {
    condition     = var.instance_count >= 1
    error_message = "instance_count must be at least 1."
  }
}
