output "kinesis_stream_name" {
  description = "Name of the inference-events Kinesis stream."
  value       = aws_kinesis_stream.inference_events.name
}

output "kinesis_stream_arn" {
  description = "ARN of the inference-events Kinesis stream."
  value       = aws_kinesis_stream.inference_events.arn
}

output "redaction_queue_url" {
  description = "URL of the redaction queue."
  value       = aws_sqs_queue.redaction.url
}

output "redaction_queue_arn" {
  description = "ARN of the redaction queue."
  value       = aws_sqs_queue.redaction.arn
}

output "redaction_dlq_arn" {
  description = "ARN of the redaction dead-letter queue."
  value       = aws_sqs_queue.redaction_dlq.arn
}

output "scoring_queue_url" {
  description = "URL of the scoring queue."
  value       = aws_sqs_queue.scoring.url
}

output "scoring_queue_arn" {
  description = "ARN of the scoring queue."
  value       = aws_sqs_queue.scoring.arn
}

output "scoring_dlq_arn" {
  description = "ARN of the scoring dead-letter queue."
  value       = aws_sqs_queue.scoring_dlq.arn
}

output "event_bus_name" {
  description = "Name of the custom EventBridge bus."
  value       = aws_cloudwatch_event_bus.main.name
}

output "event_bus_arn" {
  description = "ARN of the custom EventBridge bus."
  value       = aws_cloudwatch_event_bus.main.arn
}

output "all_queue_arns" {
  description = "ARNs of all SQS queues (primary queues and dead-letter queues)."
  value = [
    aws_sqs_queue.redaction.arn,
    aws_sqs_queue.redaction_dlq.arn,
    aws_sqs_queue.scoring.arn,
    aws_sqs_queue.scoring_dlq.arn,
    aws_sqs_queue.rl_proofs.arn,
    aws_sqs_queue.rl_proofs_dlq.arn,
  ]
}

output "rl_proofs_queue_url" {
  description = "URL of the RL proofs queue."
  value       = aws_sqs_queue.rl_proofs.url
}

output "rl_proofs_queue_arn" {
  description = "ARN of the RL proofs queue."
  value       = aws_sqs_queue.rl_proofs.arn
}

output "rl_proofs_dlq_arn" {
  description = "ARN of the RL proofs dead-letter queue."
  value       = aws_sqs_queue.rl_proofs_dlq.arn
}
