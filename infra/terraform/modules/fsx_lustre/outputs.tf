output "file_system_id" {
  description = "FSx for Lustre filesystem id (for the k8s static PV), or null when disabled."
  value       = one(aws_fsx_lustre_file_system.this[*].id)
}

output "mount_name" {
  description = "Lustre mount name required by the CSI static PV, or null when disabled."
  value       = one(aws_fsx_lustre_file_system.this[*].mount_name)
}

output "dns_name" {
  description = "Filesystem DNS name, or null when disabled."
  value       = one(aws_fsx_lustre_file_system.this[*].dns_name)
}

output "enabled" {
  description = "Whether FSx was provisioned."
  value       = var.enable_fsx
}
