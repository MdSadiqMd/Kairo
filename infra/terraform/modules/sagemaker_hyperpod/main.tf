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
  enabled = var.enable_hyperpod

  # Create an execution role only when enabled and none was supplied.
  create_execution_role = local.enabled && var.execution_role_arn == ""
  execution_role_arn    = local.enabled ? (local.create_execution_role ? aws_iam_role.execution[0].arn : var.execution_role_arn) : null

  cluster_name = "${var.name_prefix}-hyperpod"
}

data "aws_iam_policy_document" "assume_role" {
  count = local.create_execution_role ? 1 : 0

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
  count = local.create_execution_role ? 1 : 0

  name                 = "${var.name_prefix}-hyperpod-execution"
  assume_role_policy   = data.aws_iam_policy_document.assume_role[0].json
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-hyperpod-execution"
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  count = local.create_execution_role ? 1 : 0

  role       = aws_iam_role.execution[0].name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/AmazonSageMakerClusterInstanceRolePolicy"
}

# The AWS provider has no native HyperPod cluster resource, so we provision it
# through CloudFormation's AWS::SageMaker::Cluster type — the supported way to
# manage HyperPod in Terraform today. Optional and descoped from the near-term
# MVP: enabled only when var.enable_hyperpod is true.
resource "aws_cloudformation_stack" "this" {
  count = local.enabled ? 1 : 0

  name         = local.cluster_name
  capabilities = ["CAPABILITY_IAM"]

  template_body = jsonencode({
    Resources = {
      Cluster = {
        Type = "AWS::SageMaker::Cluster"
        Properties = merge(
          {
            ClusterName = local.cluster_name
            InstanceGroups = [{
              InstanceGroupName = "${var.name_prefix}-training"
              InstanceType      = var.instance_type
              InstanceCount     = var.instance_count
              ExecutionRole     = local.execution_role_arn
              LifeCycleConfig = {
                SourceS3Uri = var.lifecycle_config_s3_uri
                OnCreate    = var.lifecycle_on_create
              }
            }]
          },
          length(var.subnet_ids) > 0 ? {
            VpcConfig = {
              Subnets          = var.subnet_ids
              SecurityGroupIds = var.security_group_ids
            }
          } : {}
        )
      }
    }
    Outputs = {
      ClusterArn = { Value = { "Fn::GetAtt" = ["Cluster", "ClusterArn"] } }
    }
  })

  tags = merge(var.tags, {
    Name = local.cluster_name
  })
}
