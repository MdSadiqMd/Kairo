terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region     = var.region
  access_key = "test"
  secret_key = "test"

  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    s3             = var.aws_endpoint
    dynamodb       = var.aws_endpoint
    sqs            = var.aws_endpoint
    sns            = var.aws_endpoint
    lambda         = var.aws_endpoint
    iam            = var.aws_endpoint
    ec2            = var.aws_endpoint
    ecs            = var.aws_endpoint
    eks            = var.aws_endpoint
    ecr            = var.aws_endpoint
    cloudformation = var.aws_endpoint
    route53        = var.aws_endpoint
    cloudwatch     = var.aws_endpoint
    logs           = var.aws_endpoint
    secretsmanager = var.aws_endpoint
    ssm            = var.aws_endpoint
    kms            = var.aws_endpoint
    rds            = var.aws_endpoint
    sts            = var.aws_endpoint
    kinesis        = var.aws_endpoint
    firehose       = var.aws_endpoint
    events         = var.aws_endpoint
    wafv2          = var.aws_endpoint
    opensearch     = var.aws_endpoint
    elb            = var.aws_endpoint
    elbv2          = var.aws_endpoint
  }

  default_tags {
    tags = {
      project = var.project
      env     = var.env
      service = var.service
      model   = var.model
    }
  }
}
