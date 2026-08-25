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
    "module" = "eventing"
  })

  # A null shard_count selects on-demand capacity; a set value selects provisioned.
  stream_mode = var.shard_count == null ? "ON_DEMAND" : "PROVISIONED"

  use_kms = var.kms_key_arn != ""

  # Kinesis requires a KMS key id when encryption_type is KMS; fall back to the
  # AWS-managed alias when no CMK is supplied.
  kinesis_kms_key_id = local.use_kms ? var.kms_key_arn : "alias/aws/kinesis"
}

resource "aws_kinesis_stream" "inference_events" {
  name             = "${var.name_prefix}-inference-events"
  retention_period = var.kinesis_retention_hours
  shard_count      = var.shard_count

  stream_mode_details {
    stream_mode = local.stream_mode
  }

  encryption_type = "KMS"
  kms_key_id      = local.kinesis_kms_key_id

  tags = merge(local.common_tags, {
    "stream" = "inference-events"
  })
}

resource "aws_sqs_queue" "redaction_dlq" {
  name                      = "${var.name_prefix}-redaction-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  tags = merge(local.common_tags, { "queue" = "redaction-dlq" })
}

resource "aws_sqs_queue" "redaction" {
  name                       = "${var.name_prefix}-redaction"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.redaction_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.common_tags, { "queue" = "redaction" })
}

resource "aws_sqs_queue" "scoring_dlq" {
  name                      = "${var.name_prefix}-scoring-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  tags = merge(local.common_tags, { "queue" = "scoring-dlq" })
}

resource "aws_sqs_queue" "scoring" {
  name                       = "${var.name_prefix}-scoring"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.scoring_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.common_tags, { "queue" = "scoring" })
}

resource "aws_cloudwatch_event_bus" "main" {
  name = "${var.name_prefix}-events"

  tags = merge(local.common_tags, { "bus" = "events" })
}

# RL proofs queue for ZK-verifiable reward/eval attestation.
resource "aws_sqs_queue" "rl_proofs_dlq" {
  name                      = "${var.name_prefix}-rl-proofs-dlq"
  message_retention_seconds = var.dlq_message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  tags = merge(local.common_tags, { "queue" = "rl-proofs-dlq" })
}

resource "aws_sqs_queue" "rl_proofs" {
  name                       = "${var.name_prefix}-rl-proofs"
  visibility_timeout_seconds = 600 # proof generation can take minutes
  message_retention_seconds  = var.message_retention_seconds

  kms_master_key_id                 = local.use_kms ? var.kms_key_arn : null
  kms_data_key_reuse_period_seconds = local.use_kms ? 300 : null
  sqs_managed_sse_enabled           = local.use_kms ? null : true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rl_proofs_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = merge(local.common_tags, { "queue" = "rl-proofs" })
}
