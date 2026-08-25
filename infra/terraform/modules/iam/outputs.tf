output "role_arns" {
  value = { for k, r in aws_iam_role.service : k => r.arn }
}

output "role_names" {
  value = { for k, r in aws_iam_role.service : k => r.name }
}

output "permission_boundary_arn" {
  value = local.boundary_arn
}
