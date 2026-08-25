terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    "module" = "observability"
  })

  cloudwatch_kms_key_id = var.cloudwatch_kms_key_arn != "" ? var.cloudwatch_kms_key_arn : null
}

resource "aws_prometheus_workspace" "this" {
  alias = var.name_prefix

  tags = local.common_tags
}

data "aws_iam_policy_document" "grafana_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["grafana.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "grafana" {
  name               = "${var.name_prefix}-grafana"
  assume_role_policy = data.aws_iam_policy_document.grafana_assume_role.json

  tags = local.common_tags
}

# Grafana reads Prometheus (queries the managed workspace) and CloudWatch
# (metrics + logs) as its two managed data sources.
data "aws_iam_policy_document" "grafana" {
  statement {
    sid    = "PrometheusQuery"
    effect = "Allow"
    actions = [
      "aps:ListWorkspaces",
      "aps:DescribeWorkspace",
      "aps:QueryMetrics",
      "aps:GetLabels",
      "aps:GetSeries",
      "aps:GetMetricMetadata",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CloudWatchRead"
    effect = "Allow"
    actions = [
      "cloudwatch:DescribeAlarmsForMetric",
      "cloudwatch:DescribeAlarmHistory",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListMetrics",
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:GetInsightRuleReport",
      "logs:DescribeLogGroups",
      "logs:GetLogGroupFields",
      "logs:StartQuery",
      "logs:StopQuery",
      "logs:GetQueryResults",
      "logs:GetLogEvents",
      "tag:GetResources",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "grafana" {
  name   = "${var.name_prefix}-grafana-datasources"
  role   = aws_iam_role.grafana.id
  policy = data.aws_iam_policy_document.grafana.json
}

resource "aws_grafana_workspace" "this" {
  name                     = var.name_prefix
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = var.grafana_authentication_providers
  permission_type          = "SERVICE_MANAGED"
  data_sources             = ["PROMETHEUS", "CLOUDWATCH"]
  role_arn                 = aws_iam_role.grafana.arn

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = toset(var.log_group_components)

  name              = "/kairo/${var.name_prefix}/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = local.cloudwatch_kms_key_id

  tags = merge(local.common_tags, {
    "component" = each.value
  })
}
