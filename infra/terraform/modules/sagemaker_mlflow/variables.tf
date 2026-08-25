variable "name_prefix" {
  type        = string
  description = "Prefix applied to the tracking server, artifact bucket, IAM role, and Name tags."
}

variable "tags" {
  type        = map(string)
  description = "Additional tags merged onto every taggable resource."
  default     = {}
}

variable "kms_key_arn" {
  type        = string
  description = "Optional KMS key ARN for artifact bucket encryption and execution-role access. Empty uses SSE-S3."
  default     = ""
}

variable "mlflow_artifact_bucket" {
  type        = string
  description = "Artifact store bucket name. Empty derives <name_prefix>-mlflow-artifacts-<account>."
  default     = ""
}

variable "tracking_server_size" {
  type        = string
  description = "MLflow tracking server size (Small, Medium, Large)."
  default     = "Small"

  validation {
    condition     = contains(["Small", "Medium", "Large"], var.tracking_server_size)
    error_message = "tracking_server_size must be Small, Medium, or Large."
  }
}

variable "automatic_model_registration" {
  type        = bool
  description = "Register models logged to the tracking server in the SageMaker Model Registry automatically."
  default     = true
}

variable "mlflow_version" {
  type        = string
  description = "Optional MLflow version for the tracking server. Empty uses the service default."
  default     = ""
}

variable "permissions_boundary_arn" {
  type        = string
  description = "Optional IAM permissions boundary ARN applied to the execution role."
  default     = ""
}
