variable "name_prefix" {
  type        = string
  description = "Prefix applied to bucket names and resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "s3_kms_key_arn" {
  type        = string
  description = "ARN of the KMS CMK used for SSE-KMS on every bucket."
}

variable "force_destroy" {
  type        = bool
  description = "Allow Terraform to delete non-empty buckets on destroy."
  default     = false
}

variable "log_retention_days" {
  type        = number
  description = "Days before objects in the raw-events bucket expire."
  default     = 30
}

variable "object_lock_mode" {
  type        = string
  description = "Object Lock retention mode for the audit-logs bucket."
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.object_lock_mode)
    error_message = "object_lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "audit_log_retention_years" {
  type        = number
  description = "Object Lock retention period (in years) for the audit-logs bucket."
  default     = 7
}

variable "manage_account_public_access_block" {
  type        = bool
  description = "When true, manage the account-level S3 Block Public Access settings."
  default     = true
}

variable "enable_object_lock" {
  type        = bool
  description = "Enable Object Lock resources for audit logs. Disable only for local emulators that do not support it."
  default     = true
}

variable "enable_access_logging" {
  type        = bool
  description = "Enable S3 server access logging into the audit-log bucket. Disable only for local emulators that do not support it."
  default     = true
}
