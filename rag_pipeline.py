"""
rag_pipeline.py — governed retrieval-augmented generation for PrefectOS runs.

Three collections, one retriever:

  codebase:<run_id>   chunks of a legacy codebase being comprehended (Stage 0).
                      Replaces the 120KB digest cap in comprehension.py with
                      index-once / retrieve-per-stage.
  memory              distilled past-run records (semantic upgrade over
                      MemoryStore's keyword-overlap recall).
  regulatory          regulatory / compliance documents (RBI, PCI-DSS, SOC 2…)
                      powering the Regulatory Intelligence module.

Retrieval is *governed*: every retrieve() call can be sealed into the
decision ledger — query SHA-256, the hash of every chunk returned, and its
score — so an auditor can reconstruct exactly what context an agent saw.

Scoring:
  - BM25 (pure python, stdlib only) always works — no services, no downloads.
  - If OLLAMA_BASE_URL is set and an embedding model responds, dense cosine
    scores are blended in (hybrid). Embedding failures degrade silently to
    BM25 — a retrieval layer must never break the pipeline.

Design constraints (matching decision_ledger.py / comprehension.py):
  - stdlib only (json/math/re/urllib/hashlib) — no new hard dependencies
  - best-effort at call sites
  - append-friendly on-disk format (JSONL) under <root>/rag_index/<collection>/

CLI:
    python rag_pipeline.py ingest <path> --collection codebase:demo
    python rag_pipeline.py query  "how are payments reconciled" --collection codebase:demo
    python rag_pipeline.py stats  --collection codebase:demo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("rag_pipeline")

RAG_ROOT_NAME     = "rag_index"
CHUNKS_FILENAME   = "chunks.jsonl"
VECTORS_FILENAME  = "vectors.jsonl"

# Chunking ---------------------------------------------------------------
CODE_CHUNK_LINES    = 60      # lines per code chunk
CODE_CHUNK_OVERLAP  = 10      # overlapping lines between adjacent chunks
DOC_CHUNK_CHARS     = 1400    # target chars per prose chunk
DOC_CHUNK_OVERLAP   = 200

# Hybrid scoring ----------------------------------------------------------
BM25_K1 = 1.5
BM25_B  = 0.75
DENSE_WEIGHT = 0.5            # blend: score = (1-w)*bm25_norm + w*cosine

# Embeddings (optional, local) --------------------------------------------
OLLAMA_EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT_S   = 20

# Reuse comprehension.py's file filters so the two stages agree on what a
# "source file" is and what must never be indexed (secrets).
try:
    from comprehension import SKIP_DIRS, SOURCE_EXTS, SECRET_NAMES
except ImportError:                                    # standalone use
    SKIP_DIRS   = {".git", "node_modules", "__pycache__", ".venv", "venv",
                   "dist", "build", ".pytest_cache", "target", ".idea"}
    SOURCE_EXTS = {".py", ".js", ".ts", ".java", ".cs", ".go", ".sql", ".sh",
                   ".cbl", ".cob", ".cpy", ".pli", ".rpg", ".gs", ".gsx",
                   ".html", ".css", ".c", ".h", ".cpp", ".rb", ".php"}
    SECRET_NAMES = {".env", ".env.local", ".env.production",
                    "credentials.json", "id_rsa", "id_ed25519"}

DOC_EXTS = {".md", ".rst", ".txt", ".adoc"}

_TOKEN_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]+|\d+")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    """Lowercased identifier-friendly tokens; splits snake/camel case."""
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        # camelCase / PascalCase → parts
        parts = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tok).split()
        for p in parts:
            for sub in p.lower().split("_"):
                if len(sub) > 1:
                    out.append(sub)
    return out


# ── data model ────────────────────────────────────────────────────────────

@dataclass
class Chunk:
    chunk_id:   str            # sha256 of source_path + span + content
    source:     str            # relative path or record id
    kind:       str            # "code" | "doc" | "memory"
    span:       str            # "L120-180" or "¶3" — human-locatable
    content:    str
    meta:       dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Retrieved:
    chunk:  Chunk
    score:  float
    bm25:   float
    dense:  float | None


# ── chunkers ──────────────────────────────────────────────────────────────

def chunk_code(text: str, source: str) -> list[Chunk]:
    lines = text.splitlines()
    chunks: list[Chunk] = []
    step = CODE_CHUNK_LINES - CODE_CHUNK_OVERLAP
    for start in range(0, max(len(lines), 1), step):
        piece = lines[start:start + CODE_CHUNK_LINES]
        if not piece:
            break
        content = "\n".join(piece)
        if not content.strip():
            continue
        span = f"L{start + 1}-{start + len(piece)}"
        chunks.append(Chunk(
            chunk_id=sha256_text(f"{source}:{span}:{content}"),
            source=source, kind="code", span=span, content=content,
        ))
        if start + CODE_CHUNK_LINES >= len(lines):
            break
    return chunks


def chunk_doc(text: str, source: str, kind: str = "doc") -> list[Chunk]:
    """Split on blank lines, pack paragraphs to ~DOC_CHUNK_CHARS with overlap."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[Chunk] = []
    buf, buf_len, first_para = [], 0, 1
    for i, para in enumerate(paras, 1):
        buf.append(para); buf_len += len(para)
        if buf_len >= DOC_CHUNK_CHARS:
            content = "\n\n".join(buf)
            span = f"¶{first_para}-{i}"
            chunks.append(Chunk(
                chunk_id=sha256_text(f"{source}:{span}:{content}"),
                source=source, kind=kind, span=span, content=content,
            ))
            # start next buffer with tail overlap
            tail = content[-DOC_CHUNK_OVERLAP:]
            buf, buf_len, first_para = [tail], len(tail), i
    if buf and buf_len > 0:
        content = "\n\n".join(buf)
        span = f"¶{first_para}-{len(paras)}"
        chunks.append(Chunk(
            chunk_id=sha256_text(f"{source}:{span}:{content}"),
            source=source, kind=kind, span=span, content=content,
        ))
    return chunks


# ── optional local embeddings (Ollama) ────────────────────────────────────

class _Embedder:
    """Best-effort dense embeddings via a local Ollama server.

    Disabled unless OLLAMA_BASE_URL is set. Any failure marks the embedder
    unavailable for the rest of the process — retrieval falls back to BM25.
    """

    def __init__(self) -> None:
        self.base = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
        self._ok  = bool(self.base)

    @property
    def available(self) -> bool:
        return self._ok

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self._ok:
            return None
        out: list[list[float]] = []
        try:
            for t in texts:
                req = urllib.request.Request(
                    f"{self.base}/api/embeddings",
                    data=json.dumps({"model": OLLAMA_EMBED_MODEL,
                                     "prompt": t[:8000]}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_S) as resp:
                    vec = json.loads(resp.read()).get("embedding")
                if not vec:
                    raise ValueError("empty embedding")
                out.append(vec)
            return out
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            log.info("RAG ▶ embeddings unavailable (%s) — BM25 only", exc)
            self._ok = False
            return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a)) or 1.0
    nb  = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# ── dense backends (pluggable) ────────────────────────────────────────────
#
# chunks.jsonl is ALWAYS the source of truth (auditable flat file, BM25
# corpus). The dense backend only owns vector similarity search:
#
#   jsonl   brute-force cosine over vectors.jsonl (stdlib, default)
#   chroma  ChromaDB PersistentClient with HNSW ANN (pip install chromadb)
#
# Selected via RAG_BACKEND = jsonl | chroma | auto (default: auto — use
# chroma when importable, else jsonl). A chroma failure at init falls back
# to jsonl with a warning; retrieval must never break the pipeline.

class _JsonlDense:
    """Brute-force cosine over vectors persisted as JSONL."""
    name = "jsonl"

    def __init__(self, directory: Path) -> None:
        self.path = directory / VECTORS_FILENAME
        self._vectors: dict[str, list[float]] = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    self._vectors[d["chunk_id"]] = d["v"]
                except (json.JSONDecodeError, KeyError):
                    continue

    def __len__(self) -> int:
        return len(self._vectors)

    def add(self, ids: list[str], vectors: list[list[float]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for cid, v in zip(ids, vectors):
                if cid in self._vectors:
                    continue
                fh.write(json.dumps({"chunk_id": cid, "v": v}) + "\n")
                self._vectors[cid] = v

    def search(self, query_vec: list[float], k: int) -> dict[str, float]:
        scored = {cid: _cosine(query_vec, v) for cid, v in self._vectors.items()}
        top = sorted(scored.items(), key=lambda t: -t[1])[:k]
        return dict(top)


class _ChromaDense:
    """ChromaDB-backed ANN search. Vectors are supplied by our embedder so
    behaviour is identical across backends (no Chroma model downloads)."""
    name = "chroma"

    def __init__(self, directory: Path) -> None:
        import chromadb                                     # noqa: PLC0415
        self._client = chromadb.PersistentClient(
            path=str(directory / "chroma"))
        self._col = self._client.get_or_create_collection(
            name="dense", metadata={"hnsw:space": "cosine"})

    def __len__(self) -> int:
        return self._col.count()

    def add(self, ids: list[str], vectors: list[list[float]]) -> None:
        if ids:
            # upsert: re-adding the same chunk_id is a no-op, matching JSONL dedup
            self._col.upsert(ids=ids, embeddings=vectors)

    def search(self, query_vec: list[float], k: int) -> dict[str, float]:
        n = min(k, self._col.count())
        if n == 0:
            return {}
        res = self._col.query(query_embeddings=[query_vec], n_results=n,
                              include=["distances"])
        ids, dists = res["ids"][0], res["distances"][0]
        # chroma cosine distance = 1 - cosine similarity
        return {cid: 1.0 - d for cid, d in zip(ids, dists)}


def _make_dense_backend(directory: Path) -> "_JsonlDense | _ChromaDense":
    choice = os.getenv("RAG_BACKEND", "auto").lower()
    if choice in ("chroma", "auto"):
        try:
            backend = _ChromaDense(directory)
            log.info("RAG ▶ dense backend: chroma (%s)", directory / "chroma")
            return backend
        except Exception as exc:                            # noqa: BLE001
            if choice == "chroma":
                log.warning("RAG ▶ chroma requested but unavailable (%s) — "
                            "falling back to jsonl", exc)
            # auto: silent fall-through
    return _JsonlDense(directory)


# ── the store ─────────────────────────────────────────────────────────────

class RagStore:
    """One collection = one directory of JSONL chunk + vector files."""

    def __init__(self, root: Path | str, collection: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.:-]", "_", collection)
        self.collection = collection
        self.dir  = Path(root) / RAG_ROOT_NAME / safe
        self._lock = threading.Lock()
        self._embedder = _Embedder()
        self._chunks: dict[str, Chunk] = {}
        self._load()
        self._dense = _make_dense_backend(self.dir)

    # ── ingestion ─────────────────────────────────────────────────────────

    def ingest_path(self, path: Path | str) -> dict:
        """Walk a directory (or single file) and index code + doc files.

        Applies comprehension.py's SKIP_DIRS / SECRET_NAMES filters, so
        anything Stage 0 refuses to read, RAG refuses to index.
        """
        path = Path(path)
        files = [path] if path.is_file() else sorted(
            p for p in path.rglob("*")
            if p.is_file() and not (SKIP_DIRS & set(q.name for q in p.parents))
        )
        added, skipped_secret, seen = 0, [], 0
        for f in files:
            seen += 1
            if f.name.lower() in SECRET_NAMES or f.name.startswith(".env"):
                skipped_secret.append(str(f)); continue
            ext = f.suffix.lower()
            if ext in SOURCE_EXTS:
                chunker, kind = chunk_code, "code"
            elif ext in DOC_EXTS or f.name.lower().startswith("readme"):
                chunker, kind = chunk_doc, "doc"
            else:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = str(f.relative_to(path)) if path.is_dir() else f.name
            if chunker is chunk_doc:
                new = chunk_doc(text, rel, kind)
            else:
                new = chunk_code(text, rel)
            added += self.add_chunks(new)
        return {"files_seen": seen, "chunks_added": added,
                "skipped_secret": skipped_secret,
                "total_chunks": len(self._chunks)}

    def ingest_text(self, text: str, source: str, kind: str = "doc",
                    meta: dict | None = None) -> int:
        chunks = (chunk_code if kind == "code" else chunk_doc)(text, source)
        if meta:
            for c in chunks:
                c.meta.update(meta)
        return self.add_chunks(chunks)

    def add_chunks(self, chunks: list[Chunk]) -> int:
        """Append new chunks (dedup by chunk_id); embed if possible."""
        fresh = [c for c in chunks if c.chunk_id not in self._chunks]
        if not fresh:
            return 0
        vecs = self._embedder.embed([c.content for c in fresh]) \
               if self._embedder.available else None
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            with (self.dir / CHUNKS_FILENAME).open("a", encoding="utf-8") as fh:
                for c in fresh:
                    fh.write(json.dumps(c.as_dict(), ensure_ascii=False) + "\n")
                    self._chunks[c.chunk_id] = c
            if vecs:
                try:
                    self._dense.add([c.chunk_id for c in fresh], vecs)
                except Exception as exc:                      # noqa: BLE001
                    log.warning("RAG ▶ dense add failed (%s) — BM25 unaffected", exc)
        return len(fresh)

    # ── retrieval ─────────────────────────────────────────────────────────

    def retrieve(self, query: str, k: int = 6,
                 ledger=None, agent_id: str | None = None) -> list[Retrieved]:
        """Hybrid BM25 (+ dense if vectors exist) top-k retrieval.

        If a decision ledger is passed (or one is active via
        decision_ledger.get_ledger()), the retrieval is sealed:
        query hash, and per-chunk (source, span, content hash, score).
        """
        if not self._chunks:
            return []
        bm25 = self._bm25_scores(query)
        dense: dict[str, float] = {}
        if len(self._dense) and self._embedder.available:
            qv = self._embedder.embed([query])
            if qv:
                try:
                    # over-fetch so hybrid blending sees enough candidates
                    dense = self._dense.search(qv[0], k=max(k * 4, 20))
                except Exception as exc:                      # noqa: BLE001
                    log.warning("RAG ▶ dense search failed (%s) — BM25 only", exc)

        max_bm25 = max(bm25.values(), default=0.0) or 1.0
        results: list[Retrieved] = []
        for cid, chunk in self._chunks.items():
            b = bm25.get(cid, 0.0) / max_bm25
            d = dense.get(cid)
            score = (1 - DENSE_WEIGHT) * b + DENSE_WEIGHT * d if d is not None else b
            if score > 0:
                results.append(Retrieved(chunk, round(score, 6),
                                         round(bm25.get(cid, 0.0), 4),
                                         None if d is None else round(d, 4)))
        results.sort(key=lambda r: -r.score)
        top = results[:k]
        self._seal(query, top, ledger, agent_id)
        return top

    @staticmethod
    def render_context(results: list[Retrieved], header: str = "Retrieved context") -> str:
        """Format retrieved chunks as a prompt section with provenance lines."""
        if not results:
            return ""
        lines = [f"## {header}", "",
                 "Cite the source path and span when you rely on a chunk.", ""]
        for r in results:
            lines += [f"### {r.chunk.source}  [{r.chunk.span}]  (score {r.score:.2f})",
                      "```", r.chunk.content, "```", ""]
        return "\n".join(lines)

    def stats(self) -> dict:
        return {"collection": self.collection,
                "chunks": len(self._chunks),
                "vectors": len(self._dense),
                "dense_backend": self._dense.name,
                "embedder": self._embedder.available,
                "dir": str(self.dir)}

    # ── private ───────────────────────────────────────────────────────────

    def _seal(self, query: str, top: list[Retrieved], ledger, agent_id) -> None:
        """Best-effort ledger event — never raises."""
        try:
            if ledger is None:
                from decision_ledger import active_ledger   # type: ignore
                ledger = active_ledger()
            if ledger is None:
                return
            ledger.append(
                "rag_retrieval",
                collection=self.collection,
                agent_id=agent_id or "",
                query_sha256=sha256_text(query),
                results=[{"source": r.chunk.source, "span": r.chunk.span,
                          "chunk_sha256": sha256_text(r.chunk.content),
                          "score": r.score} for r in top],
            )
        except Exception as exc:                              # noqa: BLE001
            log.debug("RAG ▶ ledger seal skipped: %s", exc)

    def _bm25_scores(self, query: str) -> dict[str, float]:
        q = _tokens(query)
        if not q:
            return {}
        docs = {cid: _tokens(c.content) for cid, c in self._chunks.items()}
        n = len(docs)
        avgdl = (sum(len(d) for d in docs.values()) / n) if n else 1.0
        # document frequency
        df: dict[str, int] = {}
        for d in docs.values():
            for term in set(d):
                df[term] = df.get(term, 0) + 1
        scores: dict[str, float] = {}
        for cid, d in docs.items():
            dl = len(d) or 1
            tf: dict[str, int] = {}
            for t in d:
                tf[t] = tf.get(t, 0) + 1
            s = 0.0
            for term in q:
                if term not in tf:
                    continue
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                s += idf * tf[term] * (BM25_K1 + 1) / (
                    tf[term] + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl))
            if s > 0:
                scores[cid] = s
        return scores

    def _load(self) -> None:
        cpath = self.dir / CHUNKS_FILENAME
        if cpath.exists():
            for line in cpath.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    self._chunks[d["chunk_id"]] = Chunk(**d)
                except (json.JSONDecodeError, TypeError, KeyError):
                    continue


# ── module-level singleton per (root, collection) ─────────────────────────

_stores: dict[tuple[str, str], RagStore] = {}
_stores_lock = threading.Lock()


def get_store(root: Path | str, collection: str) -> RagStore:
    key = (str(root), collection)
    with _stores_lock:
        if key not in _stores:
            _stores[key] = RagStore(root, collection)
        return _stores[key]


# ── CLI ───────────────────────────────────────────────────────────────────

def _main() -> int:
    ap = argparse.ArgumentParser(description="PrefectOS governed RAG")
    ap.add_argument("command", choices=["ingest", "query", "stats"])
    ap.add_argument("target", nargs="?", help="path (ingest) or query text (query)")
    ap.add_argument("--collection", default="default")
    ap.add_argument("--root", default=".")
    ap.add_argument("-k", type=int, default=6)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    store = get_store(args.root, args.collection)

    if args.command == "ingest":
        if not args.target:
            ap.error("ingest requires a path")
        print(json.dumps(store.ingest_path(args.target), indent=2))
    elif args.command == "query":
        if not args.target:
            ap.error("query requires text")
        for r in store.retrieve(args.target, k=args.k):
            print(f"{r.score:.3f}  {r.chunk.source} [{r.chunk.span}]"
                  f"  bm25={r.bm25}" + (f" dense={r.dense}" if r.dense is not None else ""))
    else:
        print(json.dumps(store.stats(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
