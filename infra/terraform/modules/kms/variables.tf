variable "name_prefix" {
  type        = string
  description = "Prefix applied to KMS aliases and resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "deletion_window_days" {
  type        = number
  description = "Waiting period (in days) before a scheduled key deletion is finalized."
  default     = 30

  validation {
    condition     = var.deletion_window_days >= 7 && var.deletion_window_days <= 30
    error_message = "deletion_window_days must be between 7 and 30."
  }
}
