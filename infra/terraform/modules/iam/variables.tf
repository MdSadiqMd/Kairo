variable "name_prefix" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "oidc_provider_arn" {
  type        = string
  description = "ARN of the cluster IAM OIDC provider."
}

variable "oidc_provider_url" {
  type        = string
  description = "OIDC issuer URL without the https:// scheme."
}

variable "service_account_namespace" {
  type    = string
  default = "kairo"
}

variable "permission_boundary_arn" {
  type        = string
  description = "Override permission boundary ARN. Null uses the boundary policy created in this module."
  default     = null
}

variable "dynamodb_registry_table_arn" {
  type    = string
  default = ""
}

variable "dynamodb_eval_table_arn" {
  type    = string
  default = ""
}

variable "dynamodb_deployment_state_table_arn" {
  type    = string
  default = ""
}

variable "kinesis_stream_arn" {
  type    = string
  default = ""
}

variable "event_queue_arns" {
  type    = list(string)
  default = []
}

variable "agent_worker_queue_arns" {
  type    = list(string)
  default = []
}

variable "model_artifacts_bucket_arn" {
  type    = string
  default = ""
}

variable "raw_events_bucket_arn" {
  type    = string
  default = ""
}

variable "redacted_events_bucket_arn" {
  type    = string
  default = ""
}

variable "datasets_bucket_arn" {
  type    = string
  default = ""
}

variable "eval_bucket_arn" {
  type    = string
  default = ""
}

variable "eval_results_bucket_arn" {
  type    = string
  default = ""
}

variable "checkpoints_bucket_arn" {
  type    = string
  default = ""
}

variable "agent_state_bucket_arn" {
  type        = string
  default     = ""
  description = "Bucket holding agent-worker state; access is scoped to agent_state_prefix."
}

variable "agent_state_prefix" {
  type        = string
  default     = "agent-worker/*"
  description = "Key prefix inside agent_state_bucket_arn the agent-worker may read/write."
}

variable "s3_kms_key_arn" {
  type    = string
  default = ""
}

variable "hf_token_secret_arn" {
  type        = string
  default     = ""
  description = "Secrets Manager ARN for the Hugging Face token read by training jobs."
}

variable "rl_proofs_queue_arn" {
  type        = string
  default     = ""
  description = "ARN of the RL proofs SQS queue."
}

variable "proof_receipts_table_arn" {
  type        = string
  default     = ""
  description = "ARN of the proof-receipts DynamoDB table."
}

variable "proofs_bucket_arn" {
  type        = string
  default     = ""
  description = "S3 bucket ARN for proof witnesses and artifacts (model-artifacts by default)."
}
