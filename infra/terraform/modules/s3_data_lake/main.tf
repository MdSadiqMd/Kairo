terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  buckets = {
    raw_events = {
      suffix              = "raw-events"
      versioning          = false
      object_lock         = false
      intelligent_tiering = true
    }
    redacted_events = {
      suffix              = "redacted-events"
      versioning          = false
      object_lock         = false
      intelligent_tiering = false
    }
    datasets = {
      suffix              = "datasets"
      versioning          = true
      object_lock         = false
      intelligent_tiering = false
    }
    model_artifacts = {
      suffix              = "model-artifacts"
      versioning          = true
      object_lock         = false
      intelligent_tiering = false
    }
    checkpoints = {
      suffix              = "checkpoints"
      versioning          = false
      object_lock         = false
      intelligent_tiering = false
    }
    eval_results = {
      suffix              = "eval-results"
      versioning          = false
      object_lock         = false
      intelligent_tiering = false
    }
    audit_logs = {
      suffix              = "audit-logs"
      versioning          = true
      object_lock         = var.enable_object_lock
      intelligent_tiering = false
    }
  }

  versioned_buckets   = { for k, v in local.buckets : k => v if v.versioning }
  object_lock_buckets = { for k, v in local.buckets : k => v if v.object_lock }
  tiering_buckets     = { for k, v in local.buckets : k => v if v.intelligent_tiering }

  # Every bucket except audit-logs ships its server access logs to audit-logs;
  # a bucket cannot usefully log into itself.
  logging_buckets = var.enable_access_logging ? { for k, v in local.buckets : k => v if k != "audit_logs" } : {}
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket              = "${var.name_prefix}-${each.value.suffix}"
  force_destroy       = var.force_destroy
  object_lock_enabled = each.value.object_lock
  tags                = merge(var.tags, { Name = "${var.name_prefix}-${each.value.suffix}" })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.s3_kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.versioned_buckets

  bucket = aws_s3_bucket.this[each.key].id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "this" {
  for_each = local.object_lock_buckets

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    default_retention {
      mode  = var.object_lock_mode
      years = var.audit_log_retention_years
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

resource "aws_s3_bucket_intelligent_tiering_configuration" "this" {
  for_each = local.tiering_buckets

  bucket = aws_s3_bucket.this[each.key].id
  name   = "entire-bucket"

  tiering {
    access_tier = "ARCHIVE_ACCESS"
    days        = 90
  }

  tiering {
    access_tier = "DEEP_ARCHIVE_ACCESS"
    days        = 180
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "raw_events" {
  bucket = aws_s3_bucket.this["raw_events"].id

  rule {
    id     = "expire-raw-events"
    status = "Enabled"

    filter {}

    expiration {
      days = var.log_retention_days
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "checkpoints" {
  bucket = aws_s3_bucket.this["checkpoints"].id

  rule {
    id     = "tier-checkpoints"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each = local.logging_buckets

  bucket        = aws_s3_bucket.this[each.key].id
  target_bucket = aws_s3_bucket.this["audit_logs"].id
  target_prefix = "s3-access/${each.value.suffix}/"
}

data "aws_iam_policy_document" "bucket" {
  for_each = aws_s3_bucket.this

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyNonKmsPutObject"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${each.value.arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.bucket[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_account_public_access_block" "this" {
  count = var.manage_account_public_access_block ? 1 : 0

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
