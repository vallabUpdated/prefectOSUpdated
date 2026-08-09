# Part of the PrefectOS core package — batch_ingest.
"""FastAPI router: batch submission, status, SSE progress.

Wire into server.py:

    from batch_ingest.api import router as ingest_router, ingest_lifespan
    app.include_router(ingest_router)
    # and merge ingest_lifespan into your existing lifespan handler

Limits: <=100 docs per batch (the product requirement), single-page PDFs.
Autoscale signal: GET /ingest/metrics exposes queue depth for your scaler.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .worker import IngestService

MAX_BATCH = 100
UPLOAD_ROOT = Path("project_output/ingest_uploads")

router = APIRouter(prefix="/ingest", tags=["batch-ingest"])
service = IngestService()


@contextlib.asynccontextmanager
async def ingest_lifespan(app):
    await service.start()
    yield
    await service.stop()


@router.post("/batches")
async def submit_batch(user_id: str, files: list[UploadFile] = File(...)):
    if len(files) > MAX_BATCH:
        raise HTTPException(422, f"max {MAX_BATCH} documents per batch")
    batch_dir = UPLOAD_ROOT / uuid.uuid4().hex[:10]
    batch_dir.mkdir(parents=True, exist_ok=True)
    s3_bucket = os.getenv("INGEST_S3_BUCKET", "")   # set -> shared storage for ASG workers
    paths = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(415, f"{f.filename}: only PDF accepted")
        dest = batch_dir / Path(f.filename).name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        if s3_bucket:
            import boto3
            key = f"uploads/{batch_dir.name}/{dest.name}"
            boto3.client("s3").upload_file(str(dest), s3_bucket, key)
            paths.append(f"s3://{s3_bucket}/{key}")
        else:
            paths.append(str(dest))
    batch_id = await service.submit_batch(user_id, paths)
    return {"batch_id": batch_id, "accepted": len(paths)}


@router.get("/batches/{batch_id}")
async def batch_status(batch_id: str):
    state = service.batches.get(batch_id)
    if state is None:
        raise HTTPException(404, "unknown batch")
    return state.snapshot()


@router.get("/batches/{batch_id}/stream")
async def batch_stream(batch_id: str):
    if batch_id not in service.batches:
        raise HTTPException(404, "unknown batch")

    async def gen():
        while True:
            snap = service.batches[batch_id].snapshot()
            yield f"data: {json.dumps(snap)}\n\n"
            if snap["complete"]:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.get("/metrics")
async def metrics():
    return {"queue_depth": await service.queue_depth(),
            "workers": service.workers,
            "active_batches": sum(1 for b in service.batches.values()
                                  if not b.snapshot()["complete"])}
