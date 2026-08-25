terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  common_tags = merge(var.tags, {
    "module" = "dynamodb"
  })
}

# model-registry keeps one item per (role, name). Non-key item attributes carried
# by the application (version, endpoint, served_model_id, max_model_len, deployable)
# are schemaless and therefore not declared here. Only key and GSI-key attributes
# are declared. The deployable-index GSI lets the router list currently deployable
# models without a table scan.
resource "aws_dynamodb_table" "model_registry" {
  name         = "${var.name_prefix}-model-registry"
  billing_mode = var.billing_mode
  hash_key     = "role"
  range_key    = "name"

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "role"
    type = "S"
  }

  attribute {
    name = "name"
    type = "S"
  }

  attribute {
    name = "deployable"
    type = "S"
  }

  global_secondary_index {
    name            = "deployable-index"
    hash_key        = "deployable"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(local.common_tags, {
    "table" = "model-registry"
  })
}

resource "aws_dynamodb_table" "eval_run_metadata" {
  name         = "${var.name_prefix}-eval-run-metadata"
  billing_mode = var.billing_mode
  hash_key     = "eval_run_id"
  range_key    = "model_version"

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "eval_run_id"
    type = "S"
  }

  attribute {
    name = "model_version"
    type = "S"
  }

  # Query all eval runs for a given model_version across eval_run_ids.
  global_secondary_index {
    name            = "model-version-index"
    hash_key        = "model_version"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(local.common_tags, {
    "table" = "eval-run-metadata"
  })
}

resource "aws_dynamodb_table" "request_metadata" {
  name         = "${var.name_prefix}-request-metadata"
  billing_mode = var.billing_mode
  hash_key     = "request_id"
  range_key    = "tenant_id"

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "request_id"
    type = "S"
  }

  attribute {
    name = "tenant_id"
    type = "S"
  }

  ttl {
    enabled        = var.enable_ttl
    attribute_name = var.enable_ttl ? "expires_at" : ""
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(local.common_tags, {
    "table" = "request-metadata"
  })
}

resource "aws_dynamodb_table" "deployment_state" {
  name         = "${var.name_prefix}-deployment-state"
  billing_mode = var.billing_mode
  hash_key     = "environment"
  range_key    = "model_role"

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "environment"
    type = "S"
  }

  attribute {
    name = "model_role"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(local.common_tags, {
    "table" = "deployment-state"
  })
}

# Proof receipts table for ZK-verifiable RL.
resource "aws_dynamodb_table" "proof_receipts" {
  name         = "${var.name_prefix}-proof-receipts"
  billing_mode = var.billing_mode
  hash_key     = "proof_id"

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "proof_id"
    type = "S"
  }

  attribute {
    name = "subject_id"
    type = "S"
  }

  global_secondary_index {
    name            = "subject-index"
    hash_key        = "subject_id"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(local.common_tags, {
    "table" = "proof-receipts"
  })
}
