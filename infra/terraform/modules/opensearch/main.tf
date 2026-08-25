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
  common_tags = merge(var.tags, {
    "module" = "opensearch"
  })

  domain_name = var.domain_name != "" ? var.domain_name : var.name_prefix

  domain_arn = "arn:aws:es:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:domain/${local.domain_name}"

  # Default the access principal to the current account root when no explicit
  # principal ARNs are supplied. Never a public "*" wildcard.
  access_principals = length(var.access_principal_arns) > 0 ? var.access_principal_arns : ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
}

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-opensearch"
  description = "Private access to the ${local.domain_name} OpenSearch domain (HTTPS from VPC only)."
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS from within the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Allow all egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    "Name" = "${var.name_prefix}-opensearch"
  })
}

data "aws_iam_policy_document" "domain" {
  statement {
    effect  = "Allow"
    actions = ["es:ESHttp*"]

    principals {
      type        = "AWS"
      identifiers = local.access_principals
    }

    resources = ["${local.domain_arn}/*"]
  }
}

resource "aws_opensearch_domain" "this" {
  domain_name    = local.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.zone_awareness_enabled

    dynamic "zone_awareness_config" {
      for_each = var.zone_awareness_enabled ? [1] : []
      content {
        availability_zone_count = var.availability_zone_count
      }
    }

    dedicated_master_enabled = var.dedicated_master_enabled
    dedicated_master_type    = var.dedicated_master_enabled ? var.dedicated_master_type : null
    dedicated_master_count   = var.dedicated_master_enabled ? var.dedicated_master_count : null
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.volume_size
  }

  vpc_options {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.this.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = var.tls_security_policy
  }

  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = var.use_internal_user_database

    master_user_options {
      # Internal user database: username + password. IAM master: an IAM ARN.
      master_user_name     = var.use_internal_user_database ? var.master_user_name : null
      master_user_password = var.use_internal_user_database ? var.master_user_password : null
      master_user_arn      = var.use_internal_user_database ? null : var.master_user_arn
    }
  }

  access_policies = data.aws_iam_policy_document.domain.json

  tags = merge(local.common_tags, {
    "Name" = local.domain_name
  })
}
