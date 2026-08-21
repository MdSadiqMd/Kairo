"""AWS-backed event sinks (production).

Only imported when ROUTER_EVENTS_BACKEND is kinesis or sqs. The
router emits fire-and-forget structured events; the Go log_ingestor consumes
them and lands them in the S3 raw-events lake. Emission never blocks the request
path — failures are logged and dropped, not retried inline.
"""

from __future__ import annotations

from kairo_common import InferenceEvent, get_logger

from router.telemetry import EventSink

log = get_logger(__name__)


class KinesisEventSink:
    def __init__(self, stream_name: str) -> None:
        import boto3

        self._client = boto3.client("kinesis")
        self._stream = stream_name

    def emit(self, event: InferenceEvent) -> None:
        self._client.put_record(
            StreamName=self._stream,
            Data=event.to_stream_record(),
            PartitionKey=event.tenant_id,  # co-locate a tenant's events
        )


class SqsEventSink:
    def __init__(self, queue_url: str) -> None:
        import boto3

        self._client = boto3.client("sqs")
        self._queue_url = queue_url

    def emit(self, event: InferenceEvent) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=event.model_dump_json(exclude_none=True),
        )


def build_aws_sink(backend: str, stream: str) -> EventSink:
    if backend == "kinesis":
        return KinesisEventSink(stream)
    if backend == "sqs":
        return SqsEventSink(stream)
    raise ValueError(f"unknown events backend: {backend}")
