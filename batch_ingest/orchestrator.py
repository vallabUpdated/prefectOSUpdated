# Part of the PrefectOS core package — batch_ingest.
"""BatchOrchestrator — the control plane for one document batch.

One governed flow per BATCH (never per document):

    classify -> [plan gate] -> dispatch to data plane -> collect
             -> usage rollup -> seal batch chain -> master rollup

Design decisions, mirroring the Version 6 governance contract:
  - The LangGraph in core/graph.py is untouched; batches use this lighter
    orchestrator. Existing single-run pipelines behave exactly as before.
  - Classification is rules-first (extension sniff + first-page keywords);
    the pooled classifier agent is consulted only for genuinely ambiguous
    batches — same code-first philosophy as the extractor.
  - The plan gate is pluggable: pass `approve_plan=callable` for a blocking
    HITL gate (CLI/demo), or leave the default auto-approve with the
    decision recorded in the batch chain either way.
  - Document-level escalations NEVER block the batch: it completes as
    `complete_with_escalations` and reviewers clear the HITL queue
    asynchronously.
"""
from __future__ import annotations

import time
from pathlib import Path

from batch_ledger import BatchLedgerManager
from core.config import PROJECTS_ROOT, log
from core.pooled_agents import PooledAgentFactory

from .worker import IngestService


class BatchOrchestrator:
    def __init__(self, service: IngestService | None = None,
                 projects_root: Path | str = PROJECTS_ROOT):
        self.ledgers = BatchLedgerManager(projects_root)
        self.service = service or IngestService(ledger_manager=self.ledgers)
        if self.service.ledger_manager is None:
            self.service.ledger_manager = self.ledgers
        self._started = False

    async def _ensure_started(self):
        if not self._started:
            await self.service.start()
            self._started = True

    # ── the governed batch flow ─────────────────────────────────────────────

    async def run_batch(self, user_id: str, pdf_paths: list[str],
                        approve_plan=None, poll_s: float = 0.25) -> dict:
        await self._ensure_started()
        import uuid
        batch_id = f"B{uuid.uuid4().hex[:10]}"
        batch_dir = self.ledgers.batches_dir / batch_id
        batch_dir.mkdir(parents=True, exist_ok=True)

        # control-plane agents for this batch (pooled, budgeted, metered)
        pools = PooledAgentFactory(batch_id=batch_id, project_dir=batch_dir)
        resolver = pools.get("EXCEPTION_RESOLVER", role="resolver")

        # 1. classify — rules first, agent only if ambiguous
        doc_type, how = self._classify(pdf_paths)
        ledger = self.ledgers.open_batch(batch_id, user_id, len(pdf_paths))
        ledger.append("batch_classified", batch_id=batch_id,
                      doc_type=doc_type, method=how, n_docs=len(pdf_paths))

        # 2. plan gate — one human decision per batch, recorded either way
        plan = {"doc_type": doc_type, "n_docs": len(pdf_paths),
                "pipeline": "code_first_v1",
                "resolver_model": resolver.route.model,
                "resolver_tier": resolver.route.tier,
                "token_budget": pools.budget.limit}
        decision = "auto_approved" if approve_plan is None else (
            "approved" if approve_plan(plan) else "rejected")
        ledger.append("gate_decision", batch_id=batch_id, gate="processing_plan",
                      decision=decision, plan=plan)
        if decision == "rejected":
            summary = {"status": "rejected_at_plan_gate", "n_docs": len(pdf_paths)}
            self.ledgers.seal_batch(batch_id, summary)
            return {"batch_id": batch_id, **summary}

        # 3. dispatch to the data plane with the pooled resolver injected
        t0 = time.perf_counter()
        await self.service.submit_batch(user_id, pdf_paths,
                                        resolver=resolver, batch_id=batch_id)

        # 4. collect
        state = self.service.batches[batch_id]
        while not state.snapshot()["complete"]:
            import asyncio
            await asyncio.sleep(poll_s)
        snap = state.snapshot()
        snap["wall_s"] = round(time.perf_counter() - t0, 2)

        # 5. usage rollup + seal + master rollup
        usage = pools.usage_summary()
        ledger.append("batch_usage", batch_id=batch_id, **usage["token_budget"])
        status = ("complete_with_escalations" if snap["escalated"] or snap["failed"]
                  else "complete")
        summary = {"status": status, **{k: snap[k] for k in
                   ("total", "clean", "resolved_by_llm", "escalated",
                    "failed", "wall_s", "p50_ms", "p95_ms", "p99_ms")}}
        master_entry = self.ledgers.seal_batch(batch_id, summary)
        log.info("BatchOrchestrator ▶ %s sealed: %s (master seq %d)",
                 batch_id, status, master_entry["seq"])
        return {"batch_id": batch_id, **summary,
                "usage": usage, "master_seq": master_entry["seq"]}

    # ── rules-first classification ──────────────────────────────────────────

    def _classify(self, pdf_paths: list[str]) -> tuple[str, str]:
        """Sniff first page of the first few docs for statement markers.
        Returns (doc_type, method). Falls back to 'unknown' -> the pooled
        classifier agent can be wired here for mixed/ambiguous batches."""
        markers = ("ACCOUNT STATEMENT", "Opening Balance", "IFSC", "Narration")
        try:
            import pdfplumber
            for p in pdf_paths[:3]:
                with pdfplumber.open(p) as pdf:
                    text = (pdf.pages[0].extract_text() or "")[:2000]
                if sum(m in text for m in markers) >= 2:
                    return "bank_statement", "rules"
        except Exception:
            pass
        return "unknown", "rules_inconclusive"
