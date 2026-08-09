# Part of the PrefectOS core package — batch_ingest.
"""Worker-only entrypoint for Auto Scaling group instances.

Runs the IngestService loop against SQS with NO API server: ASG instances
pull documents from the shared queue, process, seal, and idle on long-poll
when the queue is empty (so scale-in is always safe).

    INGEST_SQS_URL=...  AWS_REGION=ap-south-1  INGEST_WORKERS=8 \
        python -m batch_ingest.run_worker
"""
import asyncio
import logging
import os

from .worker import IngestService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


async def main():
    workers = int(os.getenv("INGEST_WORKERS", str(os.cpu_count() or 4)))
    svc = IngestService(workers=workers)
    await svc.start()
    logging.info("worker node up: %d workers, sqs=%s",
                 workers, bool(os.getenv("INGEST_SQS_URL")))
    while True:                      # workers run in background tasks
        await asyncio.sleep(60)
        logging.info("queue depth: %s", await svc.queue_depth())


if __name__ == "__main__":
    asyncio.run(main())
