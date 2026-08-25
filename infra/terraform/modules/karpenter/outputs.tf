output "controller_role_arn" {
  description = "IRSA role ARN for the Karpenter controller service account."
  value       = aws_iam_role.controller.arn
}

output "node_role_arn" {
  description = "IAM role ARN assumed by Karpenter-launched nodes."
  value       = aws_iam_role.node.arn
}

output "node_role_name" {
  description = "IAM role name for Karpenter-launched nodes (referenced by EC2NodeClass)."
  value       = aws_iam_role.node.name
}

output "instance_profile_name" {
  description = "Instance profile name wrapping the node role."
  value       = aws_iam_instance_profile.node.name
}

output "interruption_queue_name" {
  description = "Name of the SQS interruption queue."
  value       = aws_sqs_queue.interruption.name
}

output "interruption_queue_arn" {
  description = "ARN of the SQS interruption queue."
  value       = aws_sqs_queue.interruption.arn
}

output "interruption_queue_url" {
  description = "URL of the SQS interruption queue."
  value       = aws_sqs_queue.interruption.id
}
