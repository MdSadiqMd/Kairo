# Local environment root for MiniStack emulation.
# Mirrors the prod module structure using MiniStack-compatible resources.
# This provides maximum parity with prod while running against local emulation.

moved {
  from = module.ministack.aws_s3_bucket.data_lake["raw-events"]
  to   = module.s3_data_lake.aws_s3_bucket.this["raw_events"]
}

moved {
  from = module.ministack.aws_s3_bucket.data_lake["redacted-events"]
  to   = module.s3_data_lake.aws_s3_bucket.this["redacted_events"]
}

moved {
  from = module.ministack.aws_s3_bucket.data_lake["datasets"]
  to   = module.s3_data_lake.aws_s3_bucket.this["datasets"]
}

moved {
  from = module.ministack.aws_s3_bucket.data_lake["model-artifacts"]
  to   = module.s3_data_lake.aws_s3_bucket.this["model_artifacts"]
}

moved {
  from = module.ministack.aws_s3_bucket.data_lake["checkpoints"]
  to   = module.s3_data_lake.aws_s3_bucket.this["checkpoints"]
}

moved {
  from = module.ministack.aws_s3_bucket.data_lake["eval-results"]
  to   = module.s3_data_lake.aws_s3_bucket.this["eval_results"]
}

module "kms" {
  source      = "../../modules/kms"
  name_prefix = var.name_prefix
  tags        = local.tags
}

module "s3_data_lake" {
  source                             = "../../modules/s3_data_lake"
  name_prefix                        = var.name_prefix
  s3_kms_key_arn                     = module.kms.s3_key_arn
  force_destroy                      = true
  log_retention_days                 = var.log_retention_days
  enable_object_lock                 = false
  enable_access_logging              = false
  manage_account_public_access_block = false
  tags                               = local.tags
}

module "ministack" {
  source             = "../../modules/ministack"
  name_prefix        = var.name_prefix
  region             = var.region
  cluster_name       = var.cluster_name
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = local.tags

  bucket_names = []

  dynamodb_tables = {
    "model-registry" = {
      hash_key  = "name"
      range_key = "role"
      attributes = [
        { name = "name", type = "S" },
        { name = "role", type = "S" }
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
    "proof-receipts" = {
      hash_key = "proof_id"
      attributes = [
        { name = "proof_id", type = "S" }
      ]
    }
  }

  kinesis_streams = ["inference-events"]
  sqs_queues      = ["eval-tasks", "redaction", "rl-rewards", "agent-tasks", "rl-proofs"]

  secrets = {
    "kairo-${var.env}-api-key" = {
      description     = "Router API key(s) for the ${var.env} environment"
      generate_random = true
    }
  }
}

locals {
  tags = {
    project = var.project
    env     = var.env
    service = var.service
    model   = var.model
  }
}
