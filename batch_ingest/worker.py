# Part of the PrefectOS core package — batch_ingest.
"""Batch queue + worker pool with per-document SLA enforcement.

Backends:
  - Redis (production): shared queue across worker VMs, autoscale on depth.
  - In-process asyncio (dev): zero dependencies, same interface, works on
    Windows/Git Bash for local testing.

Ledger integration (batch-sharded):
  Pass a BatchLedgerManager and every document's terminal state is sealed
  into that batch's OWN hash chain; without one, events fall back to the
  process-global decision_ledger (legacy single-run behaviour, unchanged).

Every document terminates in exactly one sealed state:
  clean | resolved_by_llm | escalated_hitl | failed
A document that would blow the SLA is escalated, never silently dropped.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .extractor import extract_statement
from .llm_exceptions import resolve_exceptions

SLA_SECONDS = float(os.getenv("INGEST_SLA_SECONDS", "10"))
WORKERS = int(os.getenv("INGEST_WORKERS", str(os.cpu_count() or 4)))
REDIS_URL = os.getenv("INGEST_REDIS_URL", "")          # empty -> in-process mode
SQS_URL = os.getenv("INGEST_SQS_URL", "")              # set -> SQS backend (AWS)
OUTPUT_ROOT = Path(os.getenv("INGEST_OUTPUT_ROOT", "project_output/ingest"))

try:
    from decision_ledger import record as ledger_record, sha256_text
except ImportError:                                     # standalone dev mode
    def ledger_record(*a, **kw): pass                    # noqa: E731
    def sha256_text(t): import hashlib; return hashlib.sha256(t.encode()).hexdigest()


@dataclass
class DocJob:
    batch_id: str
    doc_id: str
    pdf_path: str
    enqueued_at: float = field(default_factory=time.perf_counter)


@dataclass
class BatchState:
    batch_id: str
    user_id: str
    total: int
    done: int = 0
    clean: int = 0
    resolved_by_llm: int = 0
    escalated: int = 0
    failed: int = 0
    started_at: float = field(default_factory=time.time)
    per_doc_ms: list = field(default_factory=list)

    def snapshot(self) -> dict:
        ms = sorted(self.per_doc_ms)
        pct = lambda p: round(ms[min(len(ms) - 1, int(p * len(ms)))], 1) if ms else None
        return {
            "batch_id": self.batch_id, "user_id": self.user_id,
            "total": self.total, "done": self.done,
            "clean": self.clean, "resolved_by_llm": self.resolved_by_llm,
            "escalated": self.escalated, "failed": self.failed,
            "elapsed_s": round(time.time() - self.started_at, 1),
            "p50_ms": pct(0.50), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
            "complete": self.done >= self.total,
        }


class IngestService:
    """Owns the queue, the worker pool, and batch bookkeeping.

    Optional collaborators (both additive; service runs without them):
      ledger_manager  BatchLedgerManager -> per-batch sealed chains
      resolver        PooledAgent for exception adjudication (injected by
                      the BatchOrchestrator); None -> direct-API fallback
                      inside llm_exceptions, or HITL when unconfigured.
    """

    def __init__(self, workers: int = WORKERS, ledger_manager=None):
        self.workers = workers
        self.queue: asyncio.Queue[DocJob] = asyncio.Queue()
        self.batches: dict[str, BatchState] = {}
        self._tasks: list[asyncio.Task] = []
        self._redis = None
        self._sqs = None
        self.ledger_manager = ledger_manager
        self._resolvers: dict[str, object] = {}         # batch_id -> PooledAgent

    async def start(self):
        if SQS_URL:
            from .queue_sqs import SqsQueueBackend
            self._sqs = SqsQueueBackend()
        elif REDIS_URL:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(REDIS_URL)
        for i in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(i)))

    async def stop(self):
        for t in self._tasks:
            t.cancel()

    # ---- submission --------------------------------------------------------

    async def submit_batch(self, user_id: str, pdf_paths: list[str],
                           resolver=None, batch_id: str | None = None) -> str:
        batch_id = batch_id or f"B{uuid.uuid4().hex[:10]}"
        self.batches[batch_id] = BatchState(batch_id=batch_id, user_id=user_id,
                                            total=len(pdf_paths))
        if resolver is not None:
            self._resolvers[batch_id] = resolver
        if self.ledger_manager:
            self.ledger_manager.open_batch(batch_id, user_id, len(pdf_paths))
        else:
            ledger_record("batch_submitted", batch_id=batch_id,
                          user_id=user_id, n_docs=len(pdf_paths))
        jobs = [DocJob(batch_id=batch_id, doc_id=Path(p).stem, pdf_path=p)
                for p in pdf_paths]
        if self._sqs:
            await self._sqs.send_batch([j.__dict__ for j in jobs])
        elif self._redis:
            for j in jobs:
                await self._redis.rpush("ingest:q", json.dumps(j.__dict__))
        else:
            for j in jobs:
                await self.queue.put(j)
        return batch_id

    async def queue_depth(self) -> int:
        if self._sqs:
            return await self._sqs.depth()
        if self._redis:
            return int(await self._redis.llen("ingest:q"))
        return self.queue.qsize()

    # ---- worker loop -------------------------------------------------------

    async def _next_job(self):
        """Returns (job, ack) — ack is an awaitable to call AFTER the doc
        reaches a terminal state (SQS delete). None-ack for other backends."""
        if self._sqs:
            while True:
                msg = await self._sqs.receive()          # long poll, may be empty
                if msg is not None:
                    return DocJob(**msg.body), (lambda m=msg: self._sqs.ack(m))
        if self._redis:
            _, raw = await self._redis.blpop("ingest:q")
            return DocJob(**json.loads(raw)), None
        return await self.queue.get(), None

    async def _worker(self, wid: int):
        while True:
            job, ack = await self._next_job()
            state = self.batches.get(job.batch_id)
            t0 = time.perf_counter()
            budget = SLA_SECONDS - (t0 - job.enqueued_at)     # SLA includes queue wait
            try:
                outcome = await asyncio.wait_for(
                    self._process(job), timeout=max(budget, 0.5))
            except asyncio.TimeoutError:
                outcome = "escalated"
                self._seal(job, "escalated_hitl", {"reason": "sla_timeout"})
            except Exception as exc:
                outcome = "failed"
                self._seal(job, "failed", {"reason": str(exc)})
            if ack is not None:                    # terminal state reached ->
                try:                                   # remove from SQS
                    await ack()
                except Exception:
                    pass                               # retry harmless: seal is idempotent-ish
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if state:
                state.done += 1
                state.per_doc_ms.append(elapsed_ms)
                {"clean": lambda: setattr(state, "clean", state.clean + 1),
                 "resolved_by_llm": lambda: setattr(state, "resolved_by_llm", state.resolved_by_llm + 1),
                 "escalated": lambda: setattr(state, "escalated", state.escalated + 1),
                 "failed": lambda: setattr(state, "failed", state.failed + 1),
                 }.get(outcome, lambda: None)()

    @staticmethod
    def _localize(pdf_path: str) -> str:
        """s3://bucket/key -> download to /tmp so pdfplumber gets a local file.
        Local paths pass through untouched (single-VM / dev mode)."""
        if not pdf_path.startswith("s3://"):
            return pdf_path
        import tempfile, boto3
        bucket, _, key = pdf_path[5:].partition("/")
        fd, local = tempfile.mkstemp(suffix=".pdf", prefix="ingest_")
        os.close(fd)
        boto3.client("s3").download_file(bucket, key, local)
        return local

    async def _process(self, job: DocJob) -> str:
        local_path = await asyncio.to_thread(self._localize, job.pdf_path)
        # CPU-bound extraction runs in a thread so the event loop keeps serving
        result = await asyncio.to_thread(extract_statement, local_path, job.doc_id)
        if local_path != job.pdf_path:
            try: os.unlink(local_path)
            except OSError: pass

        if result.status == "clean":
            self._write_output(job, result.to_output())
            self._seal(job, "clean", {"rows": len(result.transactions)})
            return "clean"

        if result.status == "unreadable":
            self._seal(job, "escalated_hitl", {"reason": "unreadable_no_text_layer"})
            return "escalated"

        # exception path: ONLY failing rows + cached system prompt go to the LLM
        fixed = await resolve_exceptions(
            result, resolver=self._resolvers.get(job.batch_id))
        if fixed is not None:
            self._write_output(job, fixed)
            self._seal(job, "resolved_by_llm",
                       {"n_exceptions": len(result.exceptions),
                        "usage": fixed.get("usage", {})})
            return "resolved_by_llm"
        self._seal(job, "escalated_hitl", {"reason": "llm_unresolved",
                                           "n_exceptions": len(result.exceptions)})
        return "escalated"

    # ---- output + ledger ---------------------------------------------------

    def _write_output(self, job: DocJob, payload: dict):
        out_dir = OUTPUT_ROOT / job.batch_id
        out_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, default=str)
        (out_dir / f"{job.doc_id}.json").write_text(text)
        payload["_output_sha256"] = sha256_text(text)
        # per-document HTML report, generated in the same step (~10-30 ms)
        try:
            from .report import render_report
            html_text = render_report(payload, batch_id=job.batch_id)
            html_path = out_dir / f"{job.doc_id}.html"
            html_path.write_text(html_text)
            bucket = os.getenv("INGEST_S3_BUCKET", "")
            if bucket:                       # shared storage -> UI presigned links
                import boto3
                s3 = boto3.client("s3")
                for pth, ctype in ((html_path, "text/html"),
                                   (out_dir / f"{job.doc_id}.json", "application/json")):
                    s3.upload_file(str(pth), bucket,
                                   f"outputs/{job.batch_id}/{pth.name}",
                                   ExtraArgs={"ContentType": ctype})
        except Exception:
            pass                             # a report failure never fails the doc

    def _seal(self, job: DocJob, terminal_state: str, detail: dict):
        if self.ledger_manager:
            self.ledger_manager.ledger_for(job.batch_id).append(
                "doc_processed", batch_id=job.batch_id, doc_id=job.doc_id,
                terminal_state=terminal_state, **detail)
        else:
            ledger_record("doc_processed", batch_id=job.batch_id,
                          doc_id=job.doc_id, terminal_state=terminal_state,
                          **detail)
