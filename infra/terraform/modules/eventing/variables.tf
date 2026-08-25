variable "name_prefix" {
  description = "Prefix applied to every eventing resource name."
  type        = string
}

variable "tags" {
  description = "Tags merged onto every resource."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "KMS key ARN for Kinesis and SQS encryption. Empty uses AWS-managed keys (alias/aws/kinesis for Kinesis, SQS-managed SSE for queues)."
  type        = string
  default     = ""
}

variable "shard_count" {
  description = "Provisioned shard count for the Kinesis stream. Null selects ON_DEMAND capacity."
  type        = number
  default     = null
}

variable "kinesis_retention_hours" {
  description = "Kinesis stream data retention in hours (24 to 8760)."
  type        = number
  default     = 24

  validation {
    condition     = var.kinesis_retention_hours >= 24 && var.kinesis_retention_hours <= 8760
    error_message = "kinesis_retention_hours must be between 24 and 8760."
  }
}

variable "visibility_timeout_seconds" {
  description = "SQS visibility timeout for the redaction and scoring queues."
  type        = number
  default     = 300
}

variable "message_retention_seconds" {
  description = "SQS message retention for the redaction and scoring queues."
  type        = number
  default     = 345600
}

variable "dlq_message_retention_seconds" {
  description = "SQS message retention for the dead-letter queues."
  type        = number
  default     = 1209600
}

variable "max_receive_count" {
  description = "Number of receives before a message is moved to its dead-letter queue."
  type        = number
  default     = 5
}
