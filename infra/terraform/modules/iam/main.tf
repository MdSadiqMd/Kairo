terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  service_accounts = {
    router            = "router"
    inference_pod     = "inference-pod"
    log_ingestor      = "log-ingestor"
    redactor          = "redactor"
    eval_runner       = "eval-runner"
    training_job      = "training-job"
    promotion_service = "promotion-service"
    agent_worker      = "agent-worker"
    proof_worker      = "proof-worker"
  }

  boundary_arn = var.permission_boundary_arn != null ? var.permission_boundary_arn : aws_iam_policy.boundary.arn
}

data "aws_iam_policy_document" "boundary" {
  statement {
    sid    = "PlatformServiceActions"
    effect = "Allow"
    actions = [
      "s3:*",
      "dynamodb:*",
      "kinesis:*",
      "sqs:*",
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "DenyIamEscalation"
    effect = "Deny"
    actions = [
      "iam:CreatePolicy",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicy",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:AttachRolePolicy",
      "iam:AttachUserPolicy",
      "iam:AttachGroupPolicy",
      "iam:PutRolePolicy",
      "iam:PutUserPolicy",
      "iam:PutGroupPolicy",
      "iam:CreateRole",
      "iam:DeleteRolePermissionsBoundary",
      "iam:CreateUser",
      "iam:CreateAccessKey",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "DenySecurityControlTampering"
    effect = "Deny"
    actions = [
      "cloudtrail:StopLogging",
      "cloudtrail:DeleteTrail",
      "cloudtrail:UpdateTrail",
      "cloudtrail:PutEventSelectors",
      "guardduty:DeleteDetector",
      "guardduty:DisassociateFromMasterAccount",
      "guardduty:UpdateDetector",
      "guardduty:StopMonitoringMembers",
      "config:StopConfigurationRecorder",
      "config:DeleteConfigurationRecorder",
      "config:DeleteDeliveryChannel",
      "config:PutConfigurationRecorder",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "boundary" {
  name        = "${var.name_prefix}-workload-boundary"
  description = "Permission boundary for platform workload roles: caps platform actions, denies IAM escalation and security-control tampering."
  policy      = data.aws_iam_policy_document.boundary.json
  tags        = merge(var.tags, { Name = "${var.name_prefix}-workload-boundary" })
}

data "aws_iam_policy_document" "assume" {
  for_each = local.service_accounts

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:sub"
      values   = ["system:serviceaccount:${var.service_account_namespace}:${each.value}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "service" {
  for_each = local.service_accounts

  name                 = "${var.name_prefix}-${each.value}"
  assume_role_policy   = data.aws_iam_policy_document.assume[each.key].json
  permissions_boundary = local.boundary_arn
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-${each.value}" })
}

locals {
  object_arn = {
    model_artifacts = var.model_artifacts_bucket_arn == "" ? "" : "${var.model_artifacts_bucket_arn}/*"
    raw_events      = var.raw_events_bucket_arn == "" ? "" : "${var.raw_events_bucket_arn}/*"
    redacted_events = var.redacted_events_bucket_arn == "" ? "" : "${var.redacted_events_bucket_arn}/*"
    datasets        = var.datasets_bucket_arn == "" ? "" : "${var.datasets_bucket_arn}/*"
    eval            = var.eval_bucket_arn == "" ? "" : "${var.eval_bucket_arn}/*"
    eval_results    = var.eval_results_bucket_arn == "" ? "" : "${var.eval_results_bucket_arn}/*"
    checkpoints     = var.checkpoints_bucket_arn == "" ? "" : "${var.checkpoints_bucket_arn}/*"
    agent_state     = var.agent_state_bucket_arn == "" ? "" : "${var.agent_state_bucket_arn}/${var.agent_state_prefix}"
  }

  kms_arns = var.s3_kms_key_arn == "" ? [] : [var.s3_kms_key_arn]
}

data "aws_iam_policy_document" "router" {
  dynamic "statement" {
    for_each = var.dynamodb_registry_table_arn == "" ? [] : [1]
    content {
      sid       = "ReadModelRegistry"
      effect    = "Allow"
      actions   = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:DescribeTable"]
      resources = [var.dynamodb_registry_table_arn, "${var.dynamodb_registry_table_arn}/index/*"]
    }
  }

  dynamic "statement" {
    for_each = var.kinesis_stream_arn == "" ? [] : [1]
    content {
      sid       = "WriteEventsKinesis"
      effect    = "Allow"
      actions   = ["kinesis:PutRecord", "kinesis:PutRecords", "kinesis:DescribeStreamSummary"]
      resources = [var.kinesis_stream_arn]
    }
  }

  dynamic "statement" {
    for_each = length(var.event_queue_arns) == 0 ? [] : [1]
    content {
      sid       = "WriteEventsSqs"
      effect    = "Allow"
      actions   = ["sqs:SendMessage", "sqs:GetQueueAttributes"]
      resources = var.event_queue_arns
    }
  }
}

data "aws_iam_policy_document" "inference_pod" {
  dynamic "statement" {
    for_each = local.object_arn.model_artifacts == "" ? [] : [1]
    content {
      sid       = "ReadModelArtifacts"
      effect    = "Allow"
      actions   = ["s3:GetObject"]
      resources = [local.object_arn.model_artifacts]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "DecryptModelArtifacts"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }
}

data "aws_iam_policy_document" "log_ingestor" {
  dynamic "statement" {
    for_each = var.raw_events_bucket_arn == "" ? [] : [1]
    content {
      sid       = "WriteRawEvents"
      effect    = "Allow"
      actions   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucketMultipartUploads"]
      resources = [var.raw_events_bucket_arn, local.object_arn.raw_events]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "EncryptRawEvents"
      effect    = "Allow"
      actions   = ["kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }

  dynamic "statement" {
    for_each = var.kinesis_stream_arn == "" ? [] : [1]
    content {
      sid       = "ReadEventsKinesis"
      effect    = "Allow"
      actions   = ["kinesis:GetRecords", "kinesis:GetShardIterator", "kinesis:DescribeStream", "kinesis:ListShards"]
      resources = [var.kinesis_stream_arn]
    }
  }

  dynamic "statement" {
    for_each = length(var.event_queue_arns) == 0 ? [] : [1]
    content {
      sid       = "ReadEventsSqs"
      effect    = "Allow"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      resources = var.event_queue_arns
    }
  }
}

data "aws_iam_policy_document" "redactor" {
  dynamic "statement" {
    for_each = var.raw_events_bucket_arn == "" ? [] : [1]
    content {
      sid       = "ReadRawEvents"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:ListBucket"]
      resources = [var.raw_events_bucket_arn, local.object_arn.raw_events]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = var.redacted_events_bucket_arn == "" ? [] : [1]
    content {
      sid       = "WriteRedactedEvents"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = [local.object_arn.redacted_events]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "CryptRedaction"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }
}

data "aws_iam_policy_document" "eval_runner" {
  dynamic "statement" {
    for_each = (var.datasets_bucket_arn == "" && var.eval_bucket_arn == "") ? [] : [1]
    content {
      sid       = "ReadEvalInputs"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:ListBucket"]
      resources = compact([var.datasets_bucket_arn, local.object_arn.datasets, var.eval_bucket_arn, local.object_arn.eval])
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = var.eval_results_bucket_arn == "" ? [] : [1]
    content {
      sid       = "WriteEvalResults"
      effect    = "Allow"
      actions   = ["s3:PutObject"]
      resources = [local.object_arn.eval_results]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = var.dynamodb_eval_table_arn == "" ? [] : [1]
    content {
      sid       = "ReadWriteEvalTable"
      effect    = "Allow"
      actions   = ["dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:BatchWriteItem"]
      resources = [var.dynamodb_eval_table_arn, "${var.dynamodb_eval_table_arn}/index/*"]
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "CryptEval"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }
}

data "aws_iam_policy_document" "training_job" {
  dynamic "statement" {
    for_each = var.datasets_bucket_arn == "" ? [] : [1]
    content {
      sid       = "ReadDatasets"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:ListBucket"]
      resources = [var.datasets_bucket_arn, local.object_arn.datasets]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = (var.checkpoints_bucket_arn == "" && var.model_artifacts_bucket_arn == "") ? [] : [1]
    content {
      sid       = "WriteCheckpointsAndArtifacts"
      effect    = "Allow"
      actions   = ["s3:PutObject", "s3:AbortMultipartUpload", "s3:ListBucketMultipartUploads"]
      resources = compact([var.checkpoints_bucket_arn, local.object_arn.checkpoints, var.model_artifacts_bucket_arn, local.object_arn.model_artifacts])
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "CryptTraining"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }

  dynamic "statement" {
    for_each = var.hf_token_secret_arn == "" ? [] : [1]
    content {
      sid       = "ReadHfToken"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      resources = [var.hf_token_secret_arn]
    }
  }
}

data "aws_iam_policy_document" "promotion_service" {
  dynamic "statement" {
    for_each = (var.dynamodb_registry_table_arn == "" && var.dynamodb_deployment_state_table_arn == "") ? [] : [1]
    content {
      sid    = "UpdateRegistryAndDeploymentState"
      effect = "Allow"
      actions = [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DeleteItem",
      ]
      resources = compact([
        var.dynamodb_registry_table_arn,
        var.dynamodb_registry_table_arn == "" ? "" : "${var.dynamodb_registry_table_arn}/index/*",
        var.dynamodb_deployment_state_table_arn,
        var.dynamodb_deployment_state_table_arn == "" ? "" : "${var.dynamodb_deployment_state_table_arn}/index/*",
      ])
    }
  }
}

data "aws_iam_policy_document" "agent_worker" {
  dynamic "statement" {
    for_each = length(var.agent_worker_queue_arns) == 0 ? [] : [1]
    content {
      sid       = "ScopedQueue"
      effect    = "Allow"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:SendMessage", "sqs:GetQueueAttributes"]
      resources = var.agent_worker_queue_arns
    }
  }

  dynamic "statement" {
    for_each = var.agent_state_bucket_arn == "" ? [] : [1]
    content {
      sid       = "ScopedStatePrefix"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = [local.object_arn.agent_state]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }
}

data "aws_iam_policy_document" "proof_worker" {
  dynamic "statement" {
    for_each = var.rl_proofs_queue_arn == "" ? [] : [1]
    content {
      sid       = "ConsumeProofQueue"
      effect    = "Allow"
      actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:ChangeMessageVisibility"]
      resources = [var.rl_proofs_queue_arn]
    }
  }

  dynamic "statement" {
    for_each = var.proof_receipts_table_arn == "" ? [] : [1]
    content {
      sid       = "WriteProofReceipts"
      effect    = "Allow"
      actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"]
      resources = [var.proof_receipts_table_arn, "${var.proof_receipts_table_arn}/index/*"]
    }
  }

  dynamic "statement" {
    for_each = var.proofs_bucket_arn == "" ? [] : [1]
    content {
      sid       = "ReadWriteProofArtifacts"
      effect    = "Allow"
      actions   = ["s3:GetObject", "s3:PutObject"]
      resources = ["${var.proofs_bucket_arn}/proofs/*"]
      condition {
        test     = "Bool"
        variable = "aws:SecureTransport"
        values   = ["true"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(local.kms_arns) == 0 ? [] : [1]
    content {
      sid       = "CryptProofs"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
      resources = local.kms_arns
    }
  }
}

locals {
  inline_policies = {
    router            = data.aws_iam_policy_document.router.json
    inference_pod     = data.aws_iam_policy_document.inference_pod.json
    log_ingestor      = data.aws_iam_policy_document.log_ingestor.json
    redactor          = data.aws_iam_policy_document.redactor.json
    eval_runner       = data.aws_iam_policy_document.eval_runner.json
    training_job      = data.aws_iam_policy_document.training_job.json
    promotion_service = data.aws_iam_policy_document.promotion_service.json
    agent_worker      = data.aws_iam_policy_document.agent_worker.json
    proof_worker      = data.aws_iam_policy_document.proof_worker.json
  }

  active_inline_policies = {
    for k, v in local.inline_policies : k => v
    if length(jsondecode(v).Statement) > 0
  }
}

resource "aws_iam_role_policy" "service" {
  for_each = local.active_inline_policies

  name   = "${var.name_prefix}-${local.service_accounts[each.key]}"
  role   = aws_iam_role.service[each.key].id
  policy = each.value
}
