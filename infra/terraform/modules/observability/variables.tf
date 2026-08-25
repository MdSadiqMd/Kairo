variable "name_prefix" {
  description = "Prefix and alias for the Prometheus/Grafana workspaces and log group paths."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch log group retention in days."
  type        = number
  default     = 30
}

variable "cloudwatch_kms_key_arn" {
  description = "KMS key ARN for CloudWatch log group encryption. Empty uses the default CloudWatch encryption."
  type        = string
  default     = ""
}

variable "log_group_components" {
  description = "Components to create log groups for, named /kairo/<name_prefix>/<component>."
  type        = list(string)
  default = [
    "router",
    "vllm",
    "log-ingestor",
    "redactor",
    "eval-runner",
    "training",
  ]
}

variable "grafana_authentication_providers" {
  description = "Authentication providers for the Grafana workspace."
  type        = list(string)
  default     = ["AWS_SSO"]
}
