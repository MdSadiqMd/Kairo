variable "name_prefix" {
  type        = string
  description = "Prefix applied to trail name, bucket name, and resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "enable_guardduty" {
  type        = bool
  description = "Enable GuardDuty detector with S3 Protection and EKS features."
  default     = true
}

variable "guardduty_finding_frequency" {
  type        = string
  description = "Cadence at which GuardDuty publishes updated findings."
  default     = "SIX_HOURS"

  validation {
    condition     = contains(["FIFTEEN_MINUTES", "ONE_HOUR", "SIX_HOURS"], var.guardduty_finding_frequency)
    error_message = "guardduty_finding_frequency must be FIFTEEN_MINUTES, ONE_HOUR, or SIX_HOURS."
  }
}

variable "enable_security_hub" {
  type        = bool
  description = "Enable Security Hub with FSBP and CIS standards subscriptions."
  default     = true
}

variable "enable_cloudtrail" {
  type        = bool
  description = "Enable the multi-region CloudTrail with log file validation."
  default     = true
}

variable "enable_macie" {
  type        = bool
  description = "Enable Macie for continuous S3 sensitive-data scans."
  default     = true
}

variable "cloudtrail_bucket_name" {
  type        = string
  description = "Existing S3 bucket for CloudTrail logs. When empty and CloudTrail is enabled, an in-module bucket named <name_prefix>-cloudtrail-<account> is created."
  default     = ""
}

variable "cloudtrail_kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN for CloudTrail log encryption and the in-module trail bucket."
  default     = ""
}

variable "training_data_bucket_arns" {
  type        = list(string)
  description = "Training-data bucket ARNs to scope CloudTrail S3 object-level data events to."
  default     = []
}
