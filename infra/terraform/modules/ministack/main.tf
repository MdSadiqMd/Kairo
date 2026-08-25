# MiniStack compatibility wrappers for local AWS emulation.
# These resources provide MiniStack-compatible versions of AWS services
# that either don't exist in MiniStack or require different configuration.

terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  name_prefix = var.name_prefix
  ecr_repositories = {
    for name in var.ecr_repositories : name => "kairo/${name}"
  }
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-vpc"
  })
}

resource "aws_subnet" "private" {
  for_each = { for idx, az in var.availability_zones : az => idx }

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value)
  availability_zone = each.key

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

data "aws_iam_policy_document" "eks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "node_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  name               = "${local.name_prefix}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume_role.json

  tags = var.tags
}

resource "aws_iam_role" "eks_node" {
  name               = "${local.name_prefix}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume_role.json

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "eks_worker" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
  ])

  role       = aws_iam_role.eks_node.name
  policy_arn = each.value
}

resource "aws_eks_cluster" "this" {
  name     = var.cluster_name
  role_arn = aws_iam_role.eks_cluster.arn

  vpc_config {
    subnet_ids              = values(aws_subnet.private)[*].id
    endpoint_public_access  = true
    endpoint_private_access = false
  }

  tags = merge(var.tags, {
    Name = var.cluster_name
  })

  depends_on = [aws_iam_role_policy_attachment.eks_cluster]
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${local.name_prefix}-cpu"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = values(aws_subnet.private)[*].id
  instance_types  = ["t3.large"]

  scaling_config {
    desired_size = 2
    max_size     = 3
    min_size     = 1
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-cpu"
  })

  depends_on = [aws_iam_role_policy_attachment.eks_worker]
}

resource "aws_ecr_repository" "repositories" {
  for_each = local.ecr_repositories

  name                 = each.value
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

resource "aws_s3_bucket" "data_lake" {
  for_each = toset(var.bucket_names)

  bucket        = "${local.name_prefix}-${each.key}"
  force_destroy = true

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

resource "aws_dynamodb_table" "tables" {
  for_each = var.dynamodb_tables

  name         = "${local.name_prefix}-${each.key}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = each.value.hash_key
  range_key    = lookup(each.value, "range_key", null)

  dynamic "attribute" {
    for_each = each.value.attributes
    content {
      name = attribute.value.name
      type = attribute.value.type
    }
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

resource "aws_kinesis_stream" "streams" {
  for_each = toset(var.kinesis_streams)

  name             = "${local.name_prefix}-${each.key}"
  shard_count      = 1
  retention_period = 24

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

resource "aws_sqs_queue" "queues" {
  for_each = toset(var.sqs_queues)

  name = "${local.name_prefix}-${each.key}"

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-${each.key}"
  })
}

resource "aws_secretsmanager_secret" "secrets" {
  for_each = var.secrets

  name        = each.key
  description = each.value.description

  tags = merge(var.tags, {
    Name = each.key
  })
}

resource "random_password" "secret_values" {
  for_each = { for k, v in var.secrets : k => v if v.generate_random }

  length  = 40
  special = false
}

resource "aws_secretsmanager_secret_version" "secrets" {
  for_each = var.secrets

  secret_id = aws_secretsmanager_secret.secrets[each.key].id
  secret_string = each.value.generate_random ? jsonencode({
    "sk-local-${random_password.secret_values[each.key].result}" = "default"
  }) : each.value.value

  lifecycle {
    ignore_changes = [secret_string]
  }
}
