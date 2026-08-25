terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws" }
  }
}

resource "aws_efs_file_system" "this" {
  count = var.enable_efs ? 1 : 0

  encrypted        = true
  kms_key_id       = var.kms_key_arn
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-adapters"
  })
}

resource "aws_efs_mount_target" "this" {
  for_each = var.enable_efs ? toset(var.subnet_ids) : toset([])

  file_system_id  = aws_efs_file_system.this[0].id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs[0].id]
}

resource "aws_security_group" "efs" {
  count = var.enable_efs ? 1 : 0

  name        = "${var.name_prefix}-efs"
  description = "EFS mount target security group"
  vpc_id      = var.vpc_id

  ingress {
    description = "NFS from VPC"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-efs-sg"
  })
}
