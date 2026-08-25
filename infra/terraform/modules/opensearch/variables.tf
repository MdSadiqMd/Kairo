variable "name_prefix" {
  description = "Prefix for the domain and security group names."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "domain_name" {
  description = "OpenSearch domain name (3-28 lowercase chars). Empty falls back to name_prefix."
  type        = string
  default     = ""
}

variable "engine_version" {
  description = "OpenSearch engine version."
  type        = string
  default     = "OpenSearch_2.13"
}

variable "vpc_id" {
  description = "VPC ID hosting the security group for the domain."
  type        = string
}

variable "subnet_ids" {
  description = "Private-data subnet IDs the domain's ENIs attach to (one per AZ)."
  type        = list(string)
}

variable "vpc_cidr" {
  description = "VPC CIDR allowed to reach the domain on 443."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key ARN for encryption at rest."
  type        = string
}

variable "instance_type" {
  description = "Data node instance type."
  type        = string
  default     = "r6g.large.search"
}

variable "instance_count" {
  description = "Number of data nodes."
  type        = number
  default     = 2
}

variable "volume_size" {
  description = "gp3 EBS volume size per data node (GiB)."
  type        = number
  default     = 100
}

variable "zone_awareness_enabled" {
  description = "Spread data nodes across multiple AZs."
  type        = bool
  default     = true
}

variable "availability_zone_count" {
  description = "Number of AZs when zone awareness is enabled (2 or 3)."
  type        = number
  default     = 2
}

variable "dedicated_master_enabled" {
  description = "Provision dedicated master nodes."
  type        = bool
  default     = false
}

variable "dedicated_master_type" {
  description = "Instance type for dedicated master nodes."
  type        = string
  default     = "r6g.large.search"
}

variable "dedicated_master_count" {
  description = "Number of dedicated master nodes (typically 3)."
  type        = number
  default     = 3
}

variable "tls_security_policy" {
  description = "TLS security policy for the domain endpoint."
  type        = string
  default     = "Policy-Min-TLS-1-2-PFS-2023-10-07"
}

variable "use_internal_user_database" {
  description = "Use the fine-grained access control internal user database (username/password). When false, an IAM master ARN is used."
  type        = bool
  default     = true
}

variable "master_user_name" {
  description = "Internal master username (used when use_internal_user_database is true)."
  type        = string
  default     = "admin"
}

variable "master_user_password" {
  description = "Internal master password (used when use_internal_user_database is true)."
  type        = string
  sensitive   = true
  default     = null
}

variable "master_user_arn" {
  description = "IAM master ARN (used when use_internal_user_database is false)."
  type        = string
  default     = null
}

variable "access_principal_arns" {
  description = "IAM principal ARNs granted es:ESHttp* on the domain. Empty defaults to the account root. Never public."
  type        = list(string)
  default     = []
}
