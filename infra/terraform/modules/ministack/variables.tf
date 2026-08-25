variable "name_prefix" {
  description = "Prefix for all resource names."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources."
  type        = map(string)
  default     = {}
}

variable "region" {
  description = "Region passed to MiniStack-backed AWS resources."
  type        = string
  default     = "us-east-1"
}

variable "cluster_name" {
  description = "MiniStack EKS cluster name."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR for MiniStack EKS networking metadata."
  type        = string
  default     = "10.30.0.0/16"
}

variable "availability_zones" {
  description = "Availability zones for MiniStack subnet metadata."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "ecr_repositories" {
  description = "ECR repositories used by the local deploy path."
  type        = list(string)
  default     = ["router", "safety", "eval-runner", "log-ingestor", "vllm", "vllm-cpu", "training", "proof-worker"]
}

variable "bucket_names" {
  description = "List of S3 bucket name suffixes to create (prefixed with name_prefix)."
  type        = list(string)
  default = [
    "raw-events",
    "redacted-events",
    "datasets",
    "model-artifacts",
    "checkpoints",
    "eval-results",
  ]
}

variable "dynamodb_tables" {
  description = "Map of DynamoDB table configurations."
  type = map(object({
    hash_key  = string
    range_key = optional(string)
    attributes = list(object({
      name = string
      type = string
    }))
  }))
  default = {
    "model-registry" = {
      hash_key  = "model_id"
      range_key = "version"
      attributes = [
        { name = "model_id", type = "S" },
        { name = "version", type = "N" }
      ]
    }
    "request-metadata" = {
      hash_key = "request_id"
      attributes = [
        { name = "request_id", type = "S" }
      ]
    }
    "eval-run-metadata" = {
      hash_key = "run_id"
      attributes = [
        { name = "run_id", type = "S" }
      ]
    }
    "deployment-state" = {
      hash_key = "deployment_id"
      attributes = [
        { name = "deployment_id", type = "S" }
      ]
    }
  }
}

variable "kinesis_streams" {
  description = "List of Kinesis stream name suffixes to create."
  type        = list(string)
  default     = ["inference-events"]
}

variable "sqs_queues" {
  description = "List of SQS queue name suffixes to create."
  type        = list(string)
  default     = ["eval-tasks", "redaction"]
}

variable "secrets" {
  description = "Map of secrets to create in Secrets Manager."
  type = map(object({
    description     = string
    generate_random = optional(bool, false)
    value           = optional(string, "")
  }))
  default = {}
}
