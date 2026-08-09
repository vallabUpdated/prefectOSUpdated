# Part of the PrefectOS core package — batch_ingest.
"""SQS queue backend — the AWS-managed replacement for Redis.

Why SQS over Redis on AWS:
  - Nothing to run: no Redis VM to patch, back up, or size.
  - The queue depth (ApproximateNumberOfMessagesVisible) is a native
    CloudWatch metric — the Auto Scaling group scales workers on it
    directly, no custom metric plumbing.
  - Visibility timeout gives crash-safe retry for free: a worker that dies
    mid-document never loses the message; it reappears for another worker.
  - A dead-letter queue catches poison documents after N failed attempts,
    which maps cleanly onto the escalated_hitl terminal state.

Semantics vs the in-process/Redis backends:
  - receive() hides the message for VISIBILITY_TIMEOUT seconds.
  - ack() (delete) MUST be called after the document reaches a terminal
    state; otherwise the message returns and is retried.
  - After maxReceiveCount failed attempts SQS moves it to the DLQ; the
    drain_dlq() helper seals those as escalated_hitl.

Environment:
  INGEST_SQS_URL       main queue URL  (presence selects this backend)
  INGEST_SQS_DLQ_URL   dead-letter queue URL (optional, for drain_dlq)
  AWS_REGION           e.g. ap-south-1
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass

VISIBILITY_TIMEOUT = int(os.getenv("INGEST_SQS_VISIBILITY", "30"))   # > 10s SLA
WAIT_SECONDS = 10                                  # long polling: fewer API calls


@dataclass
class SqsMessage:
    body: dict
    receipt_handle: str


class SqsQueueBackend:
    def __init__(self, queue_url: str | None = None,
                 dlq_url: str | None = None, region: str | None = None):
        import boto3
        self.queue_url = queue_url or os.environ["INGEST_SQS_URL"]
        self.dlq_url = dlq_url or os.getenv("INGEST_SQS_DLQ_URL", "")
        self._sqs = boto3.client(
            "sqs", region_name=region or os.getenv("AWS_REGION", "ap-south-1"))

    # boto3 is synchronous; wrap calls in threads so the asyncio workers
    # keep serving while waiting on the network.

    async def send(self, payload: dict) -> None:
        await asyncio.to_thread(
            self._sqs.send_message,
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(payload))

    async def send_batch(self, payloads: list[dict]) -> None:
        for i in range(0, len(payloads), 10):            # SQS batch limit = 10
            entries = [{"Id": str(j), "MessageBody": json.dumps(p)}
                       for j, p in enumerate(payloads[i:i + 10])]
            await asyncio.to_thread(
                self._sqs.send_message_batch,
                QueueUrl=self.queue_url, Entries=entries)

    async def receive(self) -> SqsMessage | None:
        resp = await asyncio.to_thread(
            self._sqs.receive_message,
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=WAIT_SECONDS,
            VisibilityTimeout=VISIBILITY_TIMEOUT)
        msgs = resp.get("Messages", [])
        if not msgs:
            return None
        m = msgs[0]
        return SqsMessage(body=json.loads(m["Body"]),
                          receipt_handle=m["ReceiptHandle"])

    async def ack(self, msg: SqsMessage) -> None:
        await asyncio.to_thread(
            self._sqs.delete_message,
            QueueUrl=self.queue_url,
            ReceiptHandle=msg.receipt_handle)

    async def depth(self) -> int:
        resp = await asyncio.to_thread(
            self._sqs.get_queue_attributes,
            QueueUrl=self.queue_url,
            AttributeNames=["ApproximateNumberOfMessages"])
        return int(resp["Attributes"]["ApproximateNumberOfMessages"])

    async def drain_dlq(self, seal_fn, max_messages: int = 100) -> int:
        """Seal poison documents from the DLQ as escalated_hitl.
        `seal_fn(job_dict, reason)` is called per message. Returns count."""
        if not self.dlq_url:
            return 0
        drained = 0
        while drained < max_messages:
            resp = await asyncio.to_thread(
                self._sqs.receive_message, QueueUrl=self.dlq_url,
                MaxNumberOfMessages=10, WaitTimeSeconds=0)
            msgs = resp.get("Messages", [])
            if not msgs:
                break
            for m in msgs:
                seal_fn(json.loads(m["Body"]), "dlq_poison_document")
                await asyncio.to_thread(
                    self._sqs.delete_message, QueueUrl=self.dlq_url,
                    ReceiptHandle=m["ReceiptHandle"])
                drained += 1
        return drained
