variable "name_prefix" {
  type        = string
  description = "Prefix applied to the web ACL name, metrics, and resource Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "rate_limit" {
  type        = number
  description = "Request limit per 5-minute window per source IP before the rate-based rule blocks."
  default     = 2000
}

variable "alb_arn" {
  type        = string
  description = "ARN of the ALB to associate with the web ACL. When empty, no association is created."
  default     = ""
}

variable "enable_logging" {
  type        = bool
  description = "Enable WAF logging to a CloudWatch log group named aws-waf-logs-<name_prefix>."
  default     = true
}

variable "log_retention_days" {
  type        = number
  description = "Retention period (in days) for the WAF CloudWatch log group."
  default     = 90
}

variable "managed_rules" {
  type = list(object({
    name        = string
    vendor_name = string
    priority    = number
    metric_name = string
  }))
  description = "Optional override for the managed rule groups. When empty, the default AWS managed rule set is used."
  default     = []
}
