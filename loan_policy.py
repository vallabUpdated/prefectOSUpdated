"""
loan_policy.py — optional credit-policy retrieval for document processing.

The bank's own rules (FOIR ceilings, LTV bands, bureau cut-offs, mandatory KYC
documents) live in a policy manual, not in the operator's prompt. This module
indexes that manual once and retrieves only the clauses that bear on the run,
so the assessment cites *clause 4.2(c)* instead of inventing a threshold.

Design:

  • Off unless a policy pack is configured — no pack, no retrieval, no cost.
  • Retrieval happens ONCE per job, into the final assessment call only. The
    per-document calls never see it, so the added tokens don't multiply by the
    size of the document set.
  • Retrieved size is flat (~k chunks) whichever size the manual is: measured
    at ~1,800 tokens for k=5, whether the manual is 4 pages or 600.
  • Best-effort throughout. Any failure logs and returns nothing; a run must
    never fail because a policy lookup did.

Extraction reuses the project's own document stack (loan_processing.extract_text),
so PDF and DOCX policy manuals index the same way the loan documents are read —
rag_pipeline.ingest_path alone would only see .md/.txt.

Removal: this feature is deliberately confined. Delete this file, the
`import loan_policy` + `_attach_policy(job)` lines in loan_processing.py, the
`/loan/policy/*` routes in server.py, and the policy fields in the UI settings
dialog and card. Nothing else depends on it.

CLI:
    python loan_policy.py index  <policy_folder>
    python loan_policy.py query  <policy_folder> "FOIR ceiling and LTV limit"
    python loan_policy.py status <policy_folder>
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("orchestrator")

HERE = Path(__file__).resolve().parent
PACKS_ROOT = HERE / "policy_packs"     # indexes live here, never in the operator's folder
COLLECTION = "regulatory"

DEFAULT_K = 5                          # chunks retrieved per job
MAX_QUERY_CHARS = 1200                 # the operator prompt is the query; keep it focused
MANIFEST = "pack.json"

# Words that appear in every prompt and carry no retrieval signal. BM25 already
# down-weights common terms, but the operator prompt is instructional prose and
# these dominate it.
_STOP = {
    "you", "are", "the", "and", "for", "with", "that", "this", "from", "into",
    "each", "every", "all", "any", "must", "should", "will", "shall", "your",
    "their", "them", "they", "have", "has", "been", "being", "was", "were",
    "not", "but", "which", "when", "where", "what", "who", "how", "why",
    "return", "report", "state", "list", "give", "show", "check", "checking",
    "assess", "assessing", "review", "reviewing", "document", "documents",
    "please", "using", "use", "based", "does", "did", "can", "may", "one",
    "two", "its", "it", "as", "at", "by", "in", "of", "on", "or", "to", "is",
    "be", "a", "an", "if", "no", "do", "so", "than", "then", "there", "these",
}


@dataclass
class PolicyContext:
    """What a job retrieved, and the provenance to prove it."""
    context: str = ""                       # the prompt section, ready to append
    citations: list[dict] = field(default_factory=list)
    query: str = ""
    query_sha256: str = ""
    k: int = DEFAULT_K
    retrieve_ms: float = 0.0
    chunks_in_pack: int = 0
    pack_path: str = ""
    backend: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.context)

    def record(self) -> dict:
        """The audit record written into the run folder."""
        return {
            "pack_path": self.pack_path,
            "query": self.query,
            "query_sha256": self.query_sha256,
            "k": self.k,
            "chunks_in_pack": self.chunks_in_pack,
            "retrieve_ms": round(self.retrieve_ms, 1),
            "backend": self.backend,
            "context_chars": len(self.context),
            "citations": self.citations,
        }


# ── where a pack's index lives ───────────────────────────────────────────────

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "pack"


def pack_root(policy_path: str | Path) -> Path:
    """A stable index location per policy folder, outside the operator's folder.

    Keyed by the resolved path so two different manuals never share an index,
    and the same manual reuses its index across runs.
    """
    p = Path(policy_path).expanduser()
    digest = hashlib.sha256(str(p.resolve()).encode("utf-8")).hexdigest()[:10]
    return PACKS_ROOT / f"{_slug(p.name)}_{digest}"


def _signature(policy_path: Path) -> dict:
    """Size + mtime of every file in the pack, so an unchanged pack is skipped."""
    sig = {}
    if policy_path.is_file():
        files = [policy_path]
    else:
        files = sorted(p for p in policy_path.rglob("*") if p.is_file())
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        sig[f.name] = [st.st_size, int(st.st_mtime)]
    return sig


def _manifest_path(policy_path: str | Path) -> Path:
    return pack_root(policy_path) / MANIFEST


def _read_manifest(policy_path: str | Path) -> dict:
    try:
        return json.loads(_manifest_path(policy_path).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}


# ── indexing ─────────────────────────────────────────────────────────────────

def ensure_indexed(policy_path: str | Path, force: bool = False) -> dict:
    """Index the pack if it is new or has changed. Returns a status dict.

    Documents are read with the project's own extractor, so a PDF or DOCX
    manual indexes exactly as a PDF loan document is read.
    """
    p = Path(policy_path).expanduser()
    if not p.exists():
        return {"ok": False, "detail": f"Policy folder not found: {p}"}

    sig = _signature(p)
    if not sig:
        return {"ok": False, "detail": f"No files found in {p}"}

    prior = _read_manifest(p)
    if not force and prior.get("signature") == sig and prior.get("chunks"):
        return {**prior, "ok": True, "reused": True}

    # Imported here rather than at module scope: loan_processing imports this
    # module, and the extractor is only needed when a pack is actually indexed.
    import loan_processing as _lp
    from rag_pipeline import get_store

    root = pack_root(p)
    root.mkdir(parents=True, exist_ok=True)
    store = get_store(str(root), COLLECTION)

    supported, skipped = _lp.scan_documents(p)
    t0 = time.perf_counter()
    added, indexed, failed = 0, [], []
    for f in supported:
        try:
            text, _kind = _lp.extract_text(f)
        except Exception as exc:                                 # noqa: BLE001
            failed.append({"file": f.name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not (text or "").strip():
            failed.append({"file": f.name, "error": "no extractable text"})
            continue
        n = store.ingest_text(text, source=f.name, kind="doc",
                              meta={"pack": p.name})
        added += n
        indexed.append({"file": f.name, "chars": len(text), "chunks": n})
    elapsed_ms = (time.perf_counter() - t0) * 1000

    stats = store.stats()
    manifest = {
        "pack_path": str(p),
        "index_dir": stats["dir"],
        "signature": sig,
        "files_indexed": len(indexed),
        "files_failed": failed,
        "files_skipped": [f.name for f in skipped],
        "chunks_added": added,
        "chunks": stats["chunks"],
        "backend": stats["dense_backend"],
        "embedder": stats["embedder"],
        "index_ms": round(elapsed_ms, 1),
        "detail_per_file": indexed,
    }
    try:
        _manifest_path(p).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("policy ▶ could not write pack manifest: %s", exc)

    log.info("policy ▶ indexed %s: %d chunk(s) from %d file(s) in %.0f ms [%s]",
             p.name, added, len(indexed), elapsed_ms, stats["dense_backend"])
    return {**manifest, "ok": True, "reused": False}


def status(policy_path: str | Path) -> dict:
    """What the UI needs to show about a pack without touching the index."""
    p = Path(policy_path).expanduser()
    if not p.exists():
        return {"ok": False, "exists": False,
                "detail": f"Policy folder not found: {p}"}
    m = _read_manifest(p)
    if not m.get("chunks"):
        return {"ok": False, "exists": True, "indexed": False,
                "detail": "Not indexed yet."}
    return {"ok": True, "exists": True, "indexed": True,
            "stale": m.get("signature") != _signature(p),
            "chunks": m["chunks"], "files_indexed": m.get("files_indexed", 0),
            "backend": m.get("backend", ""), "index_dir": m.get("index_dir", ""),
            "files_failed": m.get("files_failed", [])}


# ── retrieval ────────────────────────────────────────────────────────────────

def build_query(label: str, prompt: str, extra: str = "",
                exclude: tuple[str, ...] = ()) -> str:
    """The operator prompt IS the eligibility criteria — so it is the query.

    Instructional filler ("you are assessing…", "return a JSON object…") is
    dropped so BM25 scores on the terms that name policy concepts. `exclude`
    drops the concepts code has already settled, so retrieval spends its slots
    on what is genuinely still open.
    """
    raw = f"{label} {prompt} {extra}"
    drop = {e.lower() for e in exclude}
    words, seen = [], set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9_%/-]*", raw):
        lw = w.lower()
        if lw in _STOP or lw in drop or len(lw) < 3 or lw in seen:
            continue
        seen.add(lw)
        words.append(w)
    return " ".join(words)[:MAX_QUERY_CHARS]


def retrieve(policy_path: str | Path, label: str, prompt: str,
             k: int = DEFAULT_K, agent_id: str = "PROCESSOR",
             extra: str = "", exclude: tuple[str, ...] = (),
             exclude_sources: tuple[str, ...] = ()) -> PolicyContext:
    """Retrieve the clauses that bear on this job. Never raises."""
    ctx = PolicyContext(k=k)
    try:
        p = Path(policy_path).expanduser()
        ctx.pack_path = str(p)
        state = ensure_indexed(p)
        if not state.get("ok"):
            log.warning("policy ▶ pack unavailable: %s", state.get("detail"))
            return ctx

        from rag_pipeline import get_store, RagStore
        store = get_store(str(pack_root(p)), COLLECTION)
        ctx.chunks_in_pack = store.stats()["chunks"]
        ctx.backend = store.stats()["dense_backend"]

        ctx.query = build_query(label, prompt, extra, exclude)
        ctx.query_sha256 = hashlib.sha256(ctx.query.encode("utf-8")).hexdigest()

        t0 = time.perf_counter()
        if exclude_sources:
            # Over-fetch, then drop the documents code already mined, so the
            # residual slots go to clauses the pipeline could not settle.
            hits = [h for h in store.retrieve(ctx.query, k=k + len(exclude_sources) + 3,
                                              agent_id=agent_id)
                    if h.chunk.source not in exclude_sources][:k]
        else:
            hits = store.retrieve(ctx.query, k=k, agent_id=agent_id)
        ctx.retrieve_ms = (time.perf_counter() - t0) * 1000
        if not hits:
            return ctx

        ctx.citations = [{
            "source": h.chunk.source,
            "span": h.chunk.span,
            "score": round(h.score, 4),
            "bm25": round(h.bm25, 4),
            "dense": h.dense,
            "chunk_sha256": h.chunk.chunk_id[:16],
            "preview": h.chunk.content.strip().replace("\n", " ")[:160],
        } for h in hits]

        body = RagStore.render_context(
            hits, header=("Applicable credit policy (retrieved from the bank's "
                          "own policy pack)"))
        ctx.context = (
            "\n\n" + body +
            "\nApply these clauses as the governing criteria where they speak to "
            "a question in this assessment, in preference to any general rule of "
            "thumb. Cite the source file and clause number in the basis of each "
            "check. Where the policy is silent, say so rather than inferring a "
            "threshold.\n")

        log.info("policy ▶ retrieved %d clause(s) in %.0f ms: %s",
                 len(hits), ctx.retrieve_ms,
                 ", ".join(f"{c['source']}[{c['span']}]" for c in ctx.citations))
    except Exception as exc:                                     # noqa: BLE001
        log.warning("policy ▶ retrieval skipped: %s", exc)
        return PolicyContext(k=k, pack_path=str(policy_path))
    return ctx


# ── code-side application of the policy's numeric rules ──────────────────────

# Concepts settled in code are dropped from the retrieval query, so the few
# remaining slots go to what code cannot check (documentation, tenure, conduct).
SETTLED_TERMS = ("foir", "ltv", "ratio", "ceiling", "obligation", "obligations",
                 "score", "bureau", "cibil", "value", "income")
RESIDUAL_K = 2


@dataclass
class CodedPolicy:
    """Verdicts the pipeline settled itself, with the clauses behind them."""
    checks: list[dict] = field(default_factory=list)
    context: str = ""
    rules_origin: str = ""
    rules_found: list[str] = field(default_factory=list)
    applicants: int = 0
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        """True only when code actually decided something.

        A run with no parsed figures produces nothing but "unverified", which
        is not a contribution — the caller then falls back to plain retrieval
        rather than narrowing it on the strength of empty checks.
        """
        return any(c["status"] in ("met", "not_met") for c in self.checks)

    @property
    def lean_checks(self) -> list[dict]:
        """For the fact sheet — the clause text is quoted once in the context."""
        import policy_rules as PR
        return PR.lean(self.checks)

    @property
    def sources_settled(self) -> tuple[str, ...]:
        """Policy documents retrieval should skip; code already mined them."""
        if not self.checks:
            return ()
        import policy_rules as PR
        return PR.sources_settled(self.checks)


def apply_in_code(policy_path: str | Path, fact_sheet: dict) -> CodedPolicy:
    """Select bands and compare ratios here, rather than paying a model to.

    Returns nothing when the pack has no numeric rules, or when the run has no
    parsed figures to test them against — the caller then falls back to plain
    retrieval. Never raises.
    """
    out = CodedPolicy()
    # Escape hatch: POLICY_CODE_RULES=0 falls back to plain retrieval, which is
    # also how the two strategies are A/B'd against each other.
    if os.getenv("POLICY_CODE_RULES", "1").strip().lower() in ("0", "false", "no", "off"):
        return out
    try:
        import policy_rules as PR
        t0 = time.perf_counter()
        p = Path(policy_path).expanduser()
        rules = PR.load_rules(p, index_dir=pack_root(p))
        out.rules_origin = rules.get("_origin", "")
        out.rules_found = [k for k in rules if not k.startswith("_")]
        if not out.rules_found:
            return out

        for facts in PR.facts_from_fact_sheet(fact_sheet or {}):
            out.checks.extend(PR.apply_rules(rules, facts))
            out.applicants += 1
        if not out.ok:
            # Nothing decided — no figures were parsed. Say so and let plain
            # retrieval do the work.
            log.info("policy ▶ no figures to test the policy against; "
                     "falling back to retrieval")
            return CodedPolicy(rules_origin=out.rules_origin,
                               rules_found=out.rules_found)
        out.context = PR.render_context(out.checks)
        out.elapsed_ms = (time.perf_counter() - t0) * 1000

        settled = sum(1 for c in out.checks if c["status"] in ("met", "not_met"))
        log.info("policy ▶ %d check(s) settled in code across %d applicant(s) "
                 "from %s in %.0f ms (%d decided, 0 tokens)",
                 len(out.checks), out.applicants, out.rules_origin,
                 out.elapsed_ms, settled)
    except Exception as exc:                                     # noqa: BLE001
        log.warning("policy ▶ code-side rules skipped: %s", exc)
        return CodedPolicy()
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Credit policy pack: index and query.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("index", "status"):
        s = sub.add_parser(name)
        s.add_argument("path")
        if name == "index":
            s.add_argument("--force", action="store_true")
    q = sub.add_parser("query")
    q.add_argument("path")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=DEFAULT_K)

    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.cmd == "index":
        out = ensure_indexed(args.path, force=args.force)
    elif args.cmd == "status":
        out = status(args.path)
    else:
        ctx = retrieve(args.path, "", args.text, k=args.k, agent_id="CLI")
        out = ctx.record()
        print(ctx.context or "(nothing retrieved)")
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
