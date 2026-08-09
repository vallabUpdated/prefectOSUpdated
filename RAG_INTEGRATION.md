# RAG Pipeline Integration — PrefectOS

`rag_pipeline.py` adds governed retrieval to PrefectOS. Zero new hard
dependencies (stdlib only). BM25 always works; if `OLLAMA_BASE_URL` is set
and `nomic-embed-text` is pulled (`ollama pull nomic-embed-text`), dense
hybrid scoring turns on automatically. Embedding failures degrade silently
to BM25 — retrieval can never break the pipeline.

## What "governed RAG" means here

Every `retrieve()` call is sealed into the active hash-chained decision
ledger as a `rag_retrieval` event: SHA-256 of the query, plus the source,
span, content hash, and score of every chunk returned. An auditor can
reconstruct exactly what context an agent saw — the same provenance
guarantee your approval gates already have, extended to retrieval.

```json
{"event": "rag_retrieval", "collection": "codebase:20260710_...",
 "agent_id": "COMPREHENDER", "query_sha256": "…",
 "results": [{"source": "src/payments.py", "span": "L51-110",
              "chunk_sha256": "…", "score": 0.91}]}
```

## Integration point 1 — Stage 0 comprehension  ✅ WIRED

`Orchestrator.py` is now patched: `comprehender_node` indexes the client
codebase (`codebase_indexed` ledger event, incl. dense backend used and
secrets withheld) and passes retrieved chunks to COMPREHENDER alongside
the capped digest. Downstream, PLANNER / SPEC_WRITER / EXECUTOR / TESTER
each call `_rag_codebase_context()` with a stage-appropriate query
(activity, plan excerpt, spec excerpt, test-focused) — this is the
"client wants to govern or enhance an existing product" flow: every stage
sees the real code it is about to touch, and every retrieval is sealed.

The original sketch, for reference:

```python
# Orchestrator.py — comprehender_node, after build_codebase_digest(...)
from rag_pipeline import get_store, RagStore

store = get_store(state["project_dir"], f"codebase:{state['thread_id']}")
ingest_stats = store.ingest_path(codebase)
record("codebase_indexed", **{k: v for k, v in ingest_stats.items()
                              if k != "skipped_secret"},
       secrets_skipped=len(ingest_stats["skipped_secret"]))

# keep the digest for the tree/overview, ADD targeted retrieval:
hits = store.retrieve(state["activity"], k=8, agent_id="COMPREHENDER")
rag_context = RagStore.render_context(hits, header="Most relevant code")
result = agent.invoke(
    f"Existing codebase to comprehend first:\n\n{digest}\n\n{rag_context}"
)
```

Then let **every later stage** query the same collection. In
`_EphemeralAgent` (or each node), before invoke:

```python
store = get_store(state["project_dir"], f"codebase:{state['thread_id']}")
hits = store.retrieve(user_message, k=5, agent_id=agent_id)
if hits:
    system_prompt += "\n\n" + RagStore.render_context(hits)
```

This is the change that makes Fineract-scale comprehension real: the
120KB cap becomes an overview budget, not a knowledge ceiling.

## Integration point 2 — semantic MemoryStore recall

Keep the existing keyword recall as-is (it's cheap and works), and add a
`memory` collection alongside it. In `MemoryStore.record_run`, after
writing the JSON record:

```python
from rag_pipeline import get_store
get_store(MEMORY_ROOT.parent, "memory").ingest_text(
    f"{rec.activity}\n\n{rec.plan_excerpt}\n\n{rec.requirements}\n\n{rec.test_notes}",
    source=rec.project_id, kind="doc",
    meta={"created_at": rec.created_at, "skills": rec.skills},
)
```

And in `recall()`, union RAG hits with keyword hits before ranking. With
Ollama embeddings on, "build a claims portal" now recalls the
"insurance application" runs that keyword overlap misses.

## Integration point 3 — regulatory document ingestion

This is your roadmap item "regulatory document ingestion pipeline" made
concrete. One shared collection at the repo root:

```bash
python rag_pipeline.py ingest ./regulatory_docs --collection regulatory
```

Then the Regulatory Intelligence workflow queries it per obligation:

```python
reg = get_store(".", "regulatory")
hits = reg.retrieve("outsourcing of IT services by NBFCs", k=5,
                    agent_id="PLANNER")
```

Because retrievals are ledger-sealed, "which regulation text informed this
plan" is answerable per run — that's the obligation-to-implementation
traceability the knowledge-graph module promises.

## CLI

```bash
python rag_pipeline.py ingest <path> --collection codebase:demo --root .
python rag_pipeline.py query "payment reconciliation" --collection codebase:demo --root .
python rag_pipeline.py stats --collection codebase:demo --root .
```

## On-disk layout (per collection)

```
<root>/rag_index/<collection>/
├── chunks.jsonl     append-only chunk store (dedup by content hash)
└── vectors.jsonl    optional dense vectors (only when Ollama available)
```

Append-only JSONL matches the ledger's format philosophy and survives
`--resume` (the store reloads its tail on init, like DecisionLedger).

## Config

| Env var          | Effect                                             |
|------------------|----------------------------------------------------|
| `OLLAMA_BASE_URL`| enables dense hybrid scoring (already in your .env)|
| `RAG_EMBED_MODEL`| embedding model (default `nomic-embed-text`)       |

## Dense backends (pluggable)

`chunks.jsonl` is always the source of truth (auditable flat file + BM25
corpus). The dense vector search layer is selectable:

| `RAG_BACKEND` | Behaviour                                              |
|---------------|--------------------------------------------------------|
| `auto` (def.) | ChromaDB if `pip install chromadb` succeeds, else jsonl|
| `chroma`      | ChromaDB HNSW ANN at `rag_index/<col>/chroma/`         |
| `jsonl`       | brute-force cosine over `vectors.jsonl` (stdlib)       |

Embeddings are always supplied by *our* Ollama embedder in both backends —
Chroma never downloads its own model, behaviour is identical either way,
and a Chroma failure falls back to jsonl with a warning. Add
`chromadb>=1.0` to requirements.txt for the chroma path.

## Deliberate non-goals (for now)

- No reranker. Hybrid BM25+dense is enough until demo feedback says
  otherwise.

## Tests

```bash
python -m pytest tests/test_rag_pipeline.py -q     # 9 tests
```

Covers: code/doc chunking with overlap, secret-file exclusion (`.env`,
`credentials.json` never indexed), ranking correctness, ledger sealing with
chain verification, persistence + dedup across instances, and graceful
BM25-only degradation without Ollama.
