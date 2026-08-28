terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  partition  = data.aws_partition.current.partition

  create_trail_bucket = var.enable_cloudtrail && var.cloudtrail_bucket_name == ""
  trail_bucket_name = var.cloudtrail_bucket_name != "" ? var.cloudtrail_bucket_name : (
    local.create_trail_bucket ? "${var.name_prefix}-cloudtrail-${local.account_id}" : ""
  )

  guardduty_features = var.enable_guardduty ? {
    S3_DATA_EVENTS         = "S3_DATA_EVENTS"
    EKS_AUDIT_LOGS         = "EKS_AUDIT_LOGS"
    EKS_RUNTIME_MONITORING = "EKS_RUNTIME_MONITORING"
    RUNTIME_MONITORING     = "RUNTIME_MONITORING"
  } : {}

  securityhub_standards = var.enable_security_hub ? {
    fsbp = "standards/aws-foundational-security-best-practices/v/1.0.0"
    cis  = "ruleset/cis-aws-foundations-benchmark/v/1.2.0"
  } : {}
}

resource "aws_guardduty_detector" "this" {
  count = var.enable_guardduty ? 1 : 0

  enable                       = true
  finding_publishing_frequency = var.guardduty_finding_frequency

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-guardduty"
  })
}

resource "aws_guardduty_detector_feature" "this" {
  for_each = local.guardduty_features

  detector_id = aws_guardduty_detector.this[0].id
  name        = each.value
  status      = "ENABLED"
}

resource "aws_securityhub_account" "this" {
  count = var.enable_security_hub ? 1 : 0
}

resource "aws_securityhub_standards_subscription" "this" {
  for_each = local.securityhub_standards

  standards_arn = "arn:${local.partition}:securityhub:${local.region}::${each.value}"

  depends_on = [aws_securityhub_account.this]
}

resource "aws_macie2_account" "this" {
  count = var.enable_macie ? 1 : 0
}

resource "aws_s3_bucket" "cloudtrail" {
  count = local.create_trail_bucket ? 1 : 0

  bucket        = local.trail_bucket_name
  force_destroy = false

  tags = merge(var.tags, {
    Name = local.trail_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  count = local.create_trail_bucket ? 1 : 0

  bucket = aws_s3_bucket.cloudtrail[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  count = local.create_trail_bucket ? 1 : 0

  bucket = aws_s3_bucket.cloudtrail[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  count = local.create_trail_bucket ? 1 : 0

  bucket = aws_s3_bucket.cloudtrail[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.cloudtrail_kms_key_arn != "" ? "aws:kms" : "AES256"
      kms_master_key_id = var.cloudtrail_kms_key_arn != "" ? var.cloudtrail_kms_key_arn : null
    }
    bucket_key_enabled = true
  }
}

data "aws_iam_policy_document" "cloudtrail_bucket" {
  count = local.create_trail_bucket ? 1 : 0

  statement {
    sid       = "AWSCloudTrailAclCheck"
    effect    = "Allow"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.cloudtrail[0].arn]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudtrail:${local.region}:${local.account_id}:trail/${var.name_prefix}-trail"]
    }
  }

  statement {
    sid       = "AWSCloudTrailWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.cloudtrail[0].arn}/AWSLogs/${local.account_id}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:cloudtrail:${local.region}:${local.account_id}:trail/${var.name_prefix}-trail"]
    }
  }

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.cloudtrail[0].arn, "${aws_s3_bucket.cloudtrail[0].arn}/*"]

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
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  count = local.create_trail_bucket ? 1 : 0

  bucket = aws_s3_bucket.cloudtrail[0].id
  policy = data.aws_iam_policy_document.cloudtrail_bucket[0].json
}

resource "aws_cloudtrail" "this" {
  count = var.enable_cloudtrail ? 1 : 0

  name           = "${var.name_prefix}-trail"
  s3_bucket_name = local.trail_bucket_name

  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  kms_key_id                    = var.cloudtrail_kms_key_arn != "" ? var.cloudtrail_kms_key_arn : null

  # Management events (read + write) plus S3 object-level data events scoped to the
  # training-data buckets. CloudTrail data events on training-data
  # buckets so every object read/write is auditable for the data perimeter.
  advanced_event_selector {
    name = "management-events"

    field_selector {
      field  = "eventCategory"
      equals = ["Management"]
    }
  }

  dynamic "advanced_event_selector" {
    for_each = length(var.training_data_bucket_arns) > 0 ? [1] : []

    content {
      name = "training-data-s3-object-events"

      field_selector {
        field  = "eventCategory"
        equals = ["Data"]
      }

      field_selector {
        field  = "resources.type"
        equals = ["AWS::S3::Object"]
      }

      field_selector {
        field       = "resources.ARN"
        starts_with = [for arn in var.training_data_bucket_arns : "${arn}/"]
      }
    }
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-trail"
  })

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}
