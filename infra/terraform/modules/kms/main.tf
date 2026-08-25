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

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  root_arn   = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
}

data "aws_iam_policy_document" "root_admin" {
  statement {
    sid       = "EnableRootAccountAdmin"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }
  }
}

data "aws_iam_policy_document" "s3" {
  source_policy_documents = [data.aws_iam_policy_document.root_admin.json]

  statement {
    sid    = "AllowS3ServiceUse"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:CreateGrant",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "ebs" {
  source_policy_documents = [data.aws_iam_policy_document.root_admin.json]

  statement {
    sid    = "AllowEBSServiceUse"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:CreateGrant",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ec2.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "dynamodb" {
  source_policy_documents = [data.aws_iam_policy_document.root_admin.json]

  statement {
    sid    = "AllowDynamoDBServiceUse"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:CreateGrant",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["*"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [local.account_id]
    }
  }
}

data "aws_iam_policy_document" "cloudwatch" {
  source_policy_documents = [data.aws_iam_policy_document.root_admin.json]

  # Scope the log service to log groups in this account/region via the
  # aws:logs:arn encryption context so an arbitrary group cannot use the key.
  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:*"]
    }
  }
}

data "aws_iam_policy_document" "opensearch" {
  source_policy_documents = [data.aws_iam_policy_document.root_admin.json]

  statement {
    sid    = "AllowOpenSearchServiceUse"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:CreateGrant",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["es.amazonaws.com"]
    }
  }
}

resource "aws_kms_key" "s3" {
  description             = "${var.name_prefix} S3 data-lake encryption key"
  deletion_window_in_days = var.deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.s3.json
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-s3" })
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

resource "aws_kms_key" "ebs" {
  description             = "${var.name_prefix} EBS volume encryption key"
  deletion_window_in_days = var.deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.ebs.json
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-ebs" })
}

resource "aws_kms_alias" "ebs" {
  name          = "alias/${var.name_prefix}-ebs"
  target_key_id = aws_kms_key.ebs.key_id
}

resource "aws_kms_key" "cloudwatch" {
  description             = "${var.name_prefix} CloudWatch Logs encryption key"
  deletion_window_in_days = var.deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.cloudwatch.json
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-cloudwatch" })
}

resource "aws_kms_alias" "cloudwatch" {
  name          = "alias/${var.name_prefix}-cloudwatch"
  target_key_id = aws_kms_key.cloudwatch.key_id
}

resource "aws_kms_key" "dynamodb" {
  description             = "${var.name_prefix} DynamoDB encryption key"
  deletion_window_in_days = var.deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.dynamodb.json
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-dynamodb" })
}

resource "aws_kms_alias" "dynamodb" {
  name          = "alias/${var.name_prefix}-dynamodb"
  target_key_id = aws_kms_key.dynamodb.key_id
}

resource "aws_kms_key" "opensearch" {
  description             = "${var.name_prefix} OpenSearch encryption key"
  deletion_window_in_days = var.deletion_window_days
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.opensearch.json
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-opensearch" })
}

resource "aws_kms_alias" "opensearch" {
  name          = "alias/${var.name_prefix}-opensearch"
  target_key_id = aws_kms_key.opensearch.key_id
}
