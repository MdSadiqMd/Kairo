terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# FSx for Lustre for fast shared weight loading.
# EFS is explicitly NOT usable for multi-GB/hundred-GB checkpoints — throughput
# is too low; Lustre is the correct staging layer, hydrated from S3 so pods do
# not pull weights per-cold-start from S3/HF. Count-gated: off in dev by default
# because it is an always-on priced resource.
resource "aws_fsx_lustre_file_system" "this" {
  count = var.enable_fsx ? 1 : 0

  storage_capacity            = var.storage_capacity_gib
  subnet_ids                  = [var.subnet_id]
  security_group_ids          = var.security_group_ids
  deployment_type             = "PERSISTENT_2"
  per_unit_storage_throughput = var.per_unit_throughput
  kms_key_id                  = var.kms_key_arn != "" ? var.kms_key_arn : null

  tags = merge(var.tags, { Name = "${var.name_prefix}-weights-lustre" })
}

# Link the filesystem to the model-artifacts bucket so weights hydrate on demand
# and new artifacts are auto-imported.
resource "aws_fsx_data_repository_association" "weights" {
  count = var.enable_fsx && var.model_artifacts_bucket != "" ? 1 : 0

  file_system_id       = aws_fsx_lustre_file_system.this[0].id
  data_repository_path = "s3://${var.model_artifacts_bucket}/${var.import_path_prefix}"
  file_system_path     = "/${var.import_path_prefix}"

  s3 {
    auto_export_policy {
      events = ["NEW", "CHANGED"]
    }
    auto_import_policy {
      events = ["NEW", "CHANGED"]
    }
  }
}
