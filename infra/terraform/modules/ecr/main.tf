terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  repositories = {
    router       = "router"
    vllm         = "vllm"
    vllm_cpu     = "vllm-cpu"
    safety       = "safety"
    sglang       = "sglang"
    eval_runner  = "eval-runner"
    log_ingestor = "log-ingestor"
    training     = "training"
    agent_worker = "agent-worker"
  }
}

resource "aws_ecr_repository" "this" {
  for_each = local.repositories

  # Fixed "kairo/" namespace (not name_prefix) so the repo path matches the image
  # tags produced by scripts/build_image.sh and the k8s manifest image refs
  # (kairo/<service>), keeping base manifests environment-agnostic. Repos are
  # already account/region-scoped, so no per-env prefix is needed here.
  name                 = "kairo/${each.value}"
  image_tag_mutability = var.image_tag_mutability
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = var.encryption_type
    kms_key         = var.encryption_type == "KMS" ? var.kms_key_arn : null
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-${each.value}" })
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after ${var.untagged_expire_days} days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = var.untagged_expire_days
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the last ${var.keep_last_images} images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.keep_last_images
        }
        action = { type = "expire" }
      },
    ]
  })
}

resource "aws_ecr_pull_through_cache_rule" "this" {
  count = var.enable_pull_through_cache ? 1 : 0

  ecr_repository_prefix = var.ecr_repository_prefix
  upstream_registry_url = var.upstream_registry_url
}
