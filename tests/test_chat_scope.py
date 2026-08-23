"""Scope check for the grounded chat: what reaches the model, and what doesn't.

Runs a small in/out-of-scope question set through chat_rag's retrieval gates
WITHOUT calling the model, so it costs nothing and can be run on every change
to the knobs (CHAT_RAG_MIN_BM25, CHAT_RAG_MIN_COVERAGE, CHAT_RAG_STRONG_BM25).

    python tests/test_chat_scope.py <path-to-indexed-policy-pack>

A banking question that is refused here is a false refusal; an off-topic one
that passes would reach the model, where only the prompt can stop it — and that
costs tokens. Both are printed, with the signals behind the decision.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chat_rag

IN_SCOPE = [
    "What is the maximum FOIR allowed for a housing loan?",
    "Which documents are mandatory for KYC?",
    "What LTV applies to a loan against property?",
    "How is income assessed for a self-employed applicant?",
    "What is the policy on prepayment charges?",
    "When can a loan be classified as NPA?",
    "What insurance is required against a housing loan?",
    "How are customer grievances escalated?",
]

OUT_OF_SCOPE = [
    "Who won the football match last night?",
    "Write me a poem about the sea",
    "What is the capital of France?",
    "How do I cook biryani?",
    "Recommend a good laptop for gaming",
    "What is the weather forecast for tomorrow?",
]


def probe(question: str, policy_path: str) -> dict:
    """Run the retrieval gates only — no model call."""
    from loan_policy import COLLECTION, pack_root
    from rag_pipeline import get_store

    store = get_store(str(pack_root(policy_path)), COLLECTION)
    hits = store.retrieve(chat_rag._build_query(question, []), k=chat_rag.K, agent_id="CHAT")
    if not hits:
        return {"passes": False, "why": "no hits", "bm25": 0.0, "coverage": 0.0}

    bm25 = max(h.bm25 for h in hits)
    cov = chat_rag._coverage(question, hits)
    weak = bm25 < chat_rag.MIN_BM25
    off_vocab = cov < chat_rag.MIN_COVERAGE and bm25 < chat_rag.STRONG_BM25
    return {
        "passes": not (weak or off_vocab),
        "why": "weak bm25" if weak else ("off vocabulary" if off_vocab else "covered"),
        "bm25": bm25,
        "coverage": cov,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    pack = sys.argv[1]

    from loan_policy import COLLECTION, pack_root
    from rag_pipeline import get_store
    chunks = get_store(str(pack_root(pack)), COLLECTION).stats()["chunks"]
    if not chunks:
        print(f"No index for {pack} — index the pack first (Settings ▸ Index).")
        return 2

    print(f"Pack: {pack}\n{chunks} chunks · "
          f"min_bm25={chat_rag.MIN_BM25} min_coverage={chat_rag.MIN_COVERAGE} "
          f"strong_bm25={chat_rag.STRONG_BM25}\n")

    false_refusals, leaks = [], []

    print("IN SCOPE — should reach the model")
    for q in IN_SCOPE:
        r = probe(q, pack)
        mark = "ok  " if r["passes"] else "MISS"
        if not r["passes"]:
            false_refusals.append(q)
        print(f"  {mark} bm25={r['bm25']:6.2f} cov={r['coverage']:.0%}  {q}")

    print("\nOUT OF SCOPE — should be refused for free")
    for q in OUT_OF_SCOPE:
        r = probe(q, pack)
        mark = "LEAK" if r["passes"] else "ok  "
        if r["passes"]:
            leaks.append(q)
        print(f"  {mark} bm25={r['bm25']:6.2f} cov={r['coverage']:.0%}  {q}")

    print(f"\n{len(IN_SCOPE) - len(false_refusals)}/{len(IN_SCOPE)} in-scope pass · "
          f"{len(OUT_OF_SCOPE) - len(leaks)}/{len(OUT_OF_SCOPE)} out-of-scope refused free")
    if false_refusals:
        print("False refusals (lower CHAT_RAG_MIN_COVERAGE):")
        for q in false_refusals:
            print(f"  - {q}")
    if leaks:
        print("Reached the model — the prompt gate must catch these, at token cost:")
        for q in leaks:
            print(f"  - {q}")
    return 0 if not false_refusals else 1


if __name__ == "__main__":
    sys.exit(main())
