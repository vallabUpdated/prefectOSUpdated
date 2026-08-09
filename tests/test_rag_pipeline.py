"""tests/test_rag_pipeline.py — chunking, retrieval, secrets, ledger sealing."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from rag_pipeline import (
    RagStore, chunk_code, chunk_doc, get_store, _tokens,
)
from decision_ledger import DecisionLedger, verify_file


PY_SAMPLE = "\n".join(
    [f"def payment_handler_{i}(amount, currency):" if i % 12 == 0
     else f"    ledger.append(amount)  # line {i}"
     for i in range(150)]
)

DOC_SAMPLE = "\n\n".join(
    [f"Paragraph {i}: reconciliation of settlement batches against the core "
     f"banking ledger happens nightly with double-entry checks." for i in range(20)]
)


def test_tokens_split_snake_and_camel():
    assert "payment" in _tokens("PaymentHandler process_payment")
    assert "handler" in _tokens("PaymentHandler")


def test_code_chunking_overlap_and_spans():
    chunks = chunk_code(PY_SAMPLE, "src/payments.py")
    assert len(chunks) >= 3
    assert chunks[0].span == "L1-60"
    # overlap: chunk 2 starts before chunk 1 ends
    starts = [int(c.span.split("-")[0][1:]) for c in chunks]
    assert starts[1] == 51  # 60 - 10 overlap + 1
    assert all(c.kind == "code" for c in chunks)


def test_doc_chunking_packs_paragraphs():
    chunks = chunk_doc(DOC_SAMPLE, "docs/recon.md")
    assert len(chunks) >= 2
    assert all(c.kind == "doc" for c in chunks)


def test_ingest_skips_secrets(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(PY_SAMPLE)
    (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-secret")
    (repo / "credentials.json").write_text('{"token": "x"}')
    (repo / "README.md").write_text(DOC_SAMPLE)

    store = RagStore(tmp_path / "run", "codebase:test")
    stats = store.ingest_path(repo)
    assert stats["chunks_added"] > 0
    assert any(".env" in s for s in stats["skipped_secret"])
    # secret content never indexed
    assert not any("sk-ant" in c.content for c in store._chunks.values())


def test_retrieve_ranks_relevant_chunk_first(tmp_path):
    store = RagStore(tmp_path, "t")
    store.ingest_text(PY_SAMPLE, "src/payments.py", kind="code")
    store.ingest_text("colours and shapes and unrelated prose " * 40,
                      "docs/misc.md", kind="doc")
    out = store.retrieve("payment handler ledger", k=3)
    assert out and out[0].chunk.source == "src/payments.py"
    assert out[0].score >= out[-1].score


def test_retrieval_sealed_into_hash_chained_ledger(tmp_path):
    ledger = DecisionLedger(tmp_path)
    store = RagStore(tmp_path, "codebase:run1")
    store.ingest_text(PY_SAMPLE, "src/payments.py", kind="code")
    store.retrieve("payment reconciliation", k=2, ledger=ledger,
                   agent_id="COMPREHENDER")

    ok, n, err = verify_file(tmp_path / "decision_ledger.jsonl")
    assert ok and n == 1 and err is None

    entry = json.loads((tmp_path / "decision_ledger.jsonl").read_text().splitlines()[0])
    assert entry["event"] == "rag_retrieval"
    assert entry["agent_id"] == "COMPREHENDER"
    assert len(entry["query_sha256"]) == 64
    assert all(len(r["chunk_sha256"]) == 64 for r in entry["results"])


def test_persistence_across_instances(tmp_path):
    a = RagStore(tmp_path, "persist")
    a.ingest_text(PY_SAMPLE, "src/payments.py", kind="code")
    n = len(a._chunks)
    b = RagStore(tmp_path, "persist")          # fresh load from disk
    assert len(b._chunks) == n
    # re-ingest is a no-op (dedup by chunk_id)
    assert b.ingest_text(PY_SAMPLE, "src/payments.py", kind="code") == 0


def test_bm25_only_when_no_ollama(tmp_path, monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    store = RagStore(tmp_path, "no-embed")
    store.ingest_text(PY_SAMPLE, "src/payments.py", kind="code")
    out = store.retrieve("ledger", k=1)
    assert out and out[0].dense is None        # graceful degradation


def test_backend_selection_env(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "jsonl")
    store = RagStore(tmp_path, "b1")
    assert store.stats()["dense_backend"] == "jsonl"


def test_chroma_backend_roundtrip(tmp_path, monkeypatch):
    chromadb = pytest.importorskip("chromadb")  # noqa: F841
    monkeypatch.setenv("RAG_BACKEND", "chroma")
    from rag_pipeline import _make_dense_backend
    backend = _make_dense_backend(tmp_path)
    assert backend.name == "chroma"
    backend.add(["a", "b"], [[1.0, 0.0], [0.0, 1.0]])
    assert len(backend) == 2
    hits = backend.search([1.0, 0.0], k=2)
    assert max(hits, key=hits.get) == "a"          # nearest neighbour wins
    # upsert dedup: re-adding same id doesn't grow the collection
    backend.add(["a"], [[1.0, 0.0]])
    assert len(backend) == 2


def test_chroma_fallback_to_jsonl_when_forced_but_broken(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_BACKEND", "chroma")
    import rag_pipeline as rp
    monkeypatch.setattr(rp, "_ChromaDense",
                        type("Boom", (), {"__init__": lambda self, d:
                                          (_ for _ in ()).throw(RuntimeError("no chroma"))}))
    backend = rp._make_dense_backend(tmp_path)
    assert backend.name == "jsonl"                 # graceful fallback


def test_render_context_includes_provenance(tmp_path):
    store = RagStore(tmp_path, "ctx")
    store.ingest_text(PY_SAMPLE, "src/payments.py", kind="code")
    out = store.retrieve("payment", k=1)
    text = RagStore.render_context(out, header="Codebase context")
    assert "src/payments.py" in text and "[L" in text
