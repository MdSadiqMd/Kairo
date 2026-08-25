# eventing

Async messaging backbone for the data plane: a Kinesis stream for inference
events, SQS queues for the redaction and scoring pipelines (each with a
dead-letter queue), and a custom EventBridge bus for promotion/workflow events.

## Resources

- `inference-events` Kinesis stream — ON_DEMAND by default; set `shard_count` for
  provisioned mode. Always KMS-encrypted.
- `redaction` and `scoring` SQS queues, each backed by a `*-dlq` dead-letter queue
  via a redrive policy (`max_receive_count`).
- `*-events` custom EventBridge bus.

## Key variables

| Variable | Default | Purpose |
|---|---|---|
| `name_prefix` | — | Prefix for all resource names. |
| `kms_key_arn` | `""` | CMK for Kinesis + SQS. Empty uses `alias/aws/kinesis` and SQS-managed SSE. |
| `shard_count` | `null` | Null selects ON_DEMAND; a number selects PROVISIONED. |
| `kinesis_retention_hours` | `24` | Stream retention (24–8760). |
| `visibility_timeout_seconds` | `300` | Visibility timeout for primary queues. |
| `message_retention_seconds` | `345600` | Retention for primary queues. |
| `max_receive_count` | `5` | Receives before redrive to the DLQ. |

## Key outputs

- `kinesis_stream_name`, `kinesis_stream_arn`
- `redaction_queue_url`, `redaction_queue_arn`, `redaction_dlq_arn`
- `scoring_queue_url`, `scoring_queue_arn`, `scoring_dlq_arn`
- `event_bus_name`, `event_bus_arn`
- `all_queue_arns` — list of all four queue ARNs for IAM policies.

## Notes

- When `shard_count` is null the stream runs ON_DEMAND and no shards are declared;
  switching to provisioned later is a non-destructive stream-mode change.
- SQS SSE toggles automatically: a supplied `kms_key_arn` enables CMK encryption,
  otherwise SQS-managed SSE is used (never unencrypted).
