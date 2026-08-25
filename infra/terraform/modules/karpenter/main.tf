terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  interruption_queue_name = "${var.name_prefix}-karpenter-interruption"

  # EventBridge rule definitions fanned into the interruption queue. Karpenter
  # drains and replaces nodes ahead of the terminating event.
  interruption_event_rules = {
    spot_interruption = {
      description = "EC2 Spot Instance Interruption Warning"
      event_pattern = {
        source      = ["aws.ec2"]
        detail-type = ["EC2 Spot Instance Interruption Warning"]
      }
    }
    rebalance = {
      description = "EC2 Instance Rebalance Recommendation"
      event_pattern = {
        source      = ["aws.ec2"]
        detail-type = ["EC2 Instance Rebalance Recommendation"]
      }
    }
    state_change = {
      description = "EC2 Instance State-change Notification"
      event_pattern = {
        source      = ["aws.ec2"]
        detail-type = ["EC2 Instance State-change Notification"]
      }
    }
    health_event = {
      description = "AWS Health Event"
      event_pattern = {
        source      = ["aws.health"]
        detail-type = ["AWS Health Event"]
      }
    }
  }
}

resource "aws_sqs_queue" "interruption" {
  name                      = local.interruption_queue_name
  message_retention_seconds = 300
  sqs_managed_sse_enabled   = true

  tags = merge(var.tags, {
    Name = local.interruption_queue_name
  })
}

data "aws_iam_policy_document" "interruption_queue" {
  statement {
    sid       = "AllowEventBridgeAndSqs"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.interruption.arn]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com", "sqs.amazonaws.com"]
    }
  }
}

resource "aws_sqs_queue_policy" "interruption" {
  queue_url = aws_sqs_queue.interruption.id
  policy    = data.aws_iam_policy_document.interruption_queue.json
}

resource "aws_cloudwatch_event_rule" "interruption" {
  for_each = local.interruption_event_rules

  name          = "${var.name_prefix}-karpenter-${each.key}"
  description   = each.value.description
  event_pattern = jsonencode(each.value.event_pattern)

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-karpenter-${each.key}"
  })
}

resource "aws_cloudwatch_event_target" "interruption" {
  for_each = local.interruption_event_rules

  rule      = aws_cloudwatch_event_rule.interruption[each.key].name
  target_id = "KarpenterInterruptionQueue"
  arn       = aws_sqs_queue.interruption.arn
}

data "aws_iam_policy_document" "controller_assume" {
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
      values   = ["system:serviceaccount:kube-system:karpenter"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.oidc_provider_url}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "controller" {
  name               = "${var.name_prefix}-karpenter-controller"
  assume_role_policy = data.aws_iam_policy_document.controller_assume.json

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-karpenter-controller"
  })
}

data "aws_iam_policy_document" "controller" {
  statement {
    sid    = "AllowScopedEC2Actions"
    effect = "Allow"
    actions = [
      "ec2:CreateFleet",
      "ec2:RunInstances",
      "ec2:CreateTags",
      "ec2:CreateLaunchTemplate",
      "ec2:DeleteLaunchTemplate",
      "ec2:TerminateInstances",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "AllowEC2Describe"
    effect = "Allow"
    actions = [
      "ec2:DescribeInstances",
      "ec2:DescribeInstanceTypes",
      "ec2:DescribeInstanceTypeOfferings",
      "ec2:DescribeLaunchTemplates",
      "ec2:DescribeImages",
      "ec2:DescribeSubnets",
      "ec2:DescribeSecurityGroups",
      "ec2:DescribeAvailabilityZones",
      "ec2:DescribeSpotPriceHistory",
      "ec2:DescribeCapacityReservations",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "AllowPassNodeRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.node.arn]
  }

  statement {
    sid       = "AllowPricing"
    effect    = "Allow"
    actions   = ["pricing:GetProducts"]
    resources = ["*"]
  }

  statement {
    sid       = "AllowSSMParameters"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.current.name}::parameter/aws/service/*"]
  }

  statement {
    sid       = "AllowEKSDescribe"
    effect    = "Allow"
    actions   = ["eks:DescribeCluster"]
    resources = ["arn:aws:eks:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"]
  }

  statement {
    sid    = "AllowInterruptionQueueActions"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.interruption.arn]
  }
}

resource "aws_iam_role_policy" "controller" {
  name   = "${var.name_prefix}-karpenter-controller"
  role   = aws_iam_role.controller.id
  policy = data.aws_iam_policy_document.controller.json
}

data "aws_iam_policy_document" "node_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name_prefix}-karpenter-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-karpenter-node"
  })
}

locals {
  node_managed_policies = {
    worker_node   = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
    cni           = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    ecr_read_only = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
    ssm_core      = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = local.node_managed_policies

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

resource "aws_iam_instance_profile" "node" {
  name = "${var.name_prefix}-karpenter-node"
  role = aws_iam_role.node.name

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-karpenter-node"
  })
}
