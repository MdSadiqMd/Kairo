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
  partition  = data.aws_partition.current.partition

  tracking_server_name = "${var.name_prefix}-mlflow"
  artifact_bucket_name = var.mlflow_artifact_bucket != "" ? var.mlflow_artifact_bucket : "${var.name_prefix}-mlflow-artifacts-${local.account_id}"
  artifact_store_uri   = "s3://${local.artifact_bucket_name}/"
  use_kms              = var.kms_key_arn != ""
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = local.artifact_bucket_name
  force_destroy = false

  tags = merge(var.tags, {
    Name = local.artifact_bucket_name
  })
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.use_kms ? "aws:kms" : "AES256"
      kms_master_key_id = local.use_kms ? var.kms_key_arn : null
    }
    bucket_key_enabled = true
  }
}

data "aws_iam_policy_document" "artifacts_bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]

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

resource "aws_s3_bucket_policy" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  policy = data.aws_iam_policy_document.artifacts_bucket.json
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name                 = "${var.name_prefix}-mlflow-execution"
  assume_role_policy   = data.aws_iam_policy_document.assume_role.json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-mlflow-execution"
  })
}

data "aws_iam_policy_document" "execution" {
  statement {
    sid    = "ArtifactBucketList"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid    = "ArtifactObjectAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }

  dynamic "statement" {
    for_each = local.use_kms ? [1] : []

    content {
      sid    = "ArtifactBucketKms"
      effect = "Allow"
      actions = [
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:DescribeKey",
      ]
      resources = [var.kms_key_arn]
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "${var.name_prefix}-mlflow-artifact-access"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

resource "aws_sagemaker_mlflow_tracking_server" "this" {
  tracking_server_name         = local.tracking_server_name
  artifact_store_uri           = local.artifact_store_uri
  role_arn                     = aws_iam_role.execution.arn
  tracking_server_size         = var.tracking_server_size
  automatic_model_registration = var.automatic_model_registration
  mlflow_version               = var.mlflow_version != "" ? var.mlflow_version : null

  tags = merge(var.tags, {
    Name = local.tracking_server_name
  })

  depends_on = [aws_iam_role_policy.execution]
}
