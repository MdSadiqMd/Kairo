output "file_system_id" {
  description = "EFS file system ID"
  value       = var.enable_efs ? aws_efs_file_system.this[0].id : ""
}

output "file_system_arn" {
  description = "EFS file system ARN"
  value       = var.enable_efs ? aws_efs_file_system.this[0].arn : ""
}

output "enabled" {
  description = "Whether EFS is enabled"
  value       = var.enable_efs
}
