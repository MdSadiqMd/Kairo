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
  region = var.region

  # Universal tagging: every AWS resource carries these tags via default_tags.
  # This powers the stop.sh orphan sweep, cost-allocation views, and the
  # tflint/OPA "untagged = forbidden" policy check.
  default_tags {
    tags = {
      project = var.project
      env     = var.env
      service = var.service
      model   = var.model
    }
  }
}
