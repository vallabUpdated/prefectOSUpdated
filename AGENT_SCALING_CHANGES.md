# Agent scaling changes — batch data plane (v7)

All changes are ADDITIVE. Verified byte-identical to the previous version:
core/agents.py, core/registry.py, core/skills.py, core/graph.py,
core/config.py, decision_ledger.py. Existing ephemeral agents, the LangGraph
pipeline, HITL gates, and single-run ledgers behave exactly as before.

## New modules
| File | Purpose |
|---|---|
| core/pooled_agents.py | PooledAgent + PooledAgentFactory: long-lived per-batch agents, async, cached system prompt, concurrency semaphore, per-batch TokenBudget (TokenBudgetExhaustedError extends BudgetExhaustedError) |
| core/pool_registry.py | Aggregate pool counters -> agent_pools.json (calls, in-flight, fresh/cached tokens, cache-hit %) |
| core/routing.py | Role -> model/endpoint/tier via ROUTE_* env vars; defaults fall back to WORKER_MODEL/SUPERVISOR_MODEL |
| batch_ledger.py | Per-batch ledger shards + master-chain rollup on top of unmodified decision_ledger.py; `python batch_ledger.py verify-all projects` |
| batch_ingest/ | Extractor, worker pool, exception resolver, FastAPI router, load test, BatchOrchestrator |
| claude_agents/CLAUDE_EXCEPTION_RESOLVER.md, CLAUDE_BATCH_CLASSIFIER.md | Pooled-agent definitions, same CLAUDE_*.md convention |

## Ledger layout
    projects/master_ledger/decision_ledger.jsonl       master chain
    projects/batches/<batch_id>/decision_ledger.jsonl  one chain per batch
Master `batch_sealed` entries carry each batch chain's head hash, entry
count, and file SHA-256 -> two-level verification. The in-browser Decision
Ledger viewer can verify any batch file as-is; following master->batch links
is a small UI addition (not included here).

## Test evidence (this build, run in CI sandbox)
- 2 concurrent batches (20 + 10 docs, 2 corrupted): statuses
  complete_with_escalations / complete; chains verified, head+digest match
  master; tampering 1 byte -> verify-all exit 1 at the exact line.
- Plan-gate rejection -> rejected_at_plan_gate, halt-on-reject preserved.
- TokenBudget: cache reads excluded from spend; exhaustion raises through
  the existing BudgetExhaustedError hierarchy.
- New modules import without langchain (lazy anthropic import only).

## Environment
BATCH_TOKEN_BUDGET (500000), POOL_MAX_CONCURRENCY (16),
ROUTE_RESOLVER_MODEL / ROUTE_RESOLVER_BASE_URL / ROUTE_API_KEY (LiteLLM),
plus batch_ingest INGEST_* vars (see batch_ingest/README_BATCH_INGEST.md).

## Usage
    from batch_ingest.orchestrator import BatchOrchestrator
    orch = BatchOrchestrator()
    result = await orch.run_batch(user_id, pdf_paths)          # auto gate
    result = await orch.run_batch(user_id, paths, approve_plan=cb)  # HITL gate
