# Part of the PrefectOS core package — batch_ingest.
"""Burst load test: N_USERS concurrent batches of N_DOCS single-page PDFs.

Runs against IngestService in-process (no HTTP overhead) so it measures the
pipeline itself. Point it at real hardware to validate the SLA before a
client demo:

    python -m batch_ingest.load_test --users 50 --docs 100 --sample path.pdf

On a dev laptop, start with --users 5 --docs 20 and extrapolate: throughput
scales ~linearly with vCPUs for the CPU-bound clean path.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import statistics
import time
from pathlib import Path

from .worker import IngestService


async def main(users: int, docs: int, sample: str, workers: int):
    work = Path("loadtest_docs")
    work.mkdir(exist_ok=True)
    # one physical copy per doc so filesystem behaviour matches production
    paths = []
    for i in range(docs):
        p = work / f"doc_{i:04d}.pdf"
        if not p.exists():
            shutil.copy(sample, p)
        paths.append(str(p))

    svc = IngestService(workers=workers)
    await svc.start()

    t0 = time.perf_counter()
    batch_ids = await asyncio.gather(*[
        svc.submit_batch(f"user_{u:03d}", paths) for u in range(users)])

    while True:
        await asyncio.sleep(0.5)
        snaps = [svc.batches[b].snapshot() for b in batch_ids]
        done = sum(s["done"] for s in snaps)
        total = users * docs
        print(f"\r{done}/{total} docs  depth={await svc.queue_depth()}",
              end="", flush=True)
        if all(s["complete"] for s in snaps):
            break
    wall = time.perf_counter() - t0

    all_ms = [ms for b in batch_ids for ms in svc.batches[b].per_doc_ms]
    all_ms.sort()
    q = lambda p: all_ms[int(p * (len(all_ms) - 1))]
    print(f"\n\ndocs: {len(all_ms)}  wall: {wall:.1f}s  "
          f"throughput: {len(all_ms)/wall:.1f} docs/s")
    print(f"per-doc  p50: {q(.5):.0f}ms  p95: {q(.95):.0f}ms  "
          f"p99: {q(.99):.0f}ms  max: {max(all_ms):.0f}ms  "
          f"mean: {statistics.mean(all_ms):.0f}ms")
    sla_ok = sum(1 for ms in all_ms if ms <= 10_000)
    print(f"SLA (<=10s incl. queue wait): {sla_ok}/{len(all_ms)} "
          f"({100*sla_ok/len(all_ms):.2f}%)")
    clean = sum(svc.batches[b].clean for b in batch_ids)
    esc = sum(svc.batches[b].escalated for b in batch_ids)
    print(f"clean: {clean}  escalated: {esc}")
    await svc.stop()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=5)
    ap.add_argument("--docs", type=int, default=20)
    ap.add_argument("--workers", type=int, default=0, help="0 = cpu_count")
    ap.add_argument("--sample", required=True)
    a = ap.parse_args()
    import os
    asyncio.run(main(a.users, a.docs, a.sample,
                     a.workers or (os.cpu_count() or 4)))
