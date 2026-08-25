variable "name_prefix" {
  description = "Prefix applied to every table name (e.g. kairo-cloud-dev)."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "KMS key ARN used for DynamoDB server-side encryption. When empty, DynamoDB uses an AWS-owned key."
  type        = string
  default     = ""
}

variable "billing_mode" {
  description = "DynamoDB billing mode."
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.billing_mode)
    error_message = "billing_mode must be PAY_PER_REQUEST or PROVISIONED."
  }
}

variable "deletion_protection" {
  description = "Enable deletion protection on all tables."
  type        = bool
  default     = true
}

variable "enable_ttl" {
  description = "Enable TTL on the request-metadata table (expires_at attribute)."
  type        = bool
  default     = true
}
