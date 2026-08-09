"""batch_ledger.py — per-batch ledger shards with a master-chain rollup.

Built ON TOP of decision_ledger.py (unmodified). Structure:

    projects/master_ledger/decision_ledger.jsonl      <- master chain
    projects/batches/<batch_id>/decision_ledger.jsonl <- one chain per batch

Each batch gets its own hash chain: gate decisions, agent spawns, and one
terminal-state entry per document — so 50 users' bursts never interleave and
per-batch append throughput scales with the number of batches.

When a batch is sealed, the master chain receives one `batch_sealed` entry
carrying the batch chain's head hash, entry count, and the SHA-256 of the
batch ledger file. Two-level verification:

    verify master chain      -> trust every batch summary
    verify any batch chain   -> audit that batch's documents; its recomputed
                                head must equal `batch_head_hash` in master

CLI:
    python batch_ledger.py verify-all [projects_root]
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from decision_ledger import (DecisionLedger, verify_file, sha256_text,
                             LEDGER_FILENAME)

MASTER_DIRNAME = "master_ledger"
BATCHES_DIRNAME = "batches"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BatchLedgerManager:
    """Owns the master chain and hands out per-batch ledger shards."""

    def __init__(self, projects_root: Path | str):
        self.projects_root = Path(projects_root)
        self.master_dir = self.projects_root / MASTER_DIRNAME
        self.batches_dir = self.projects_root / BATCHES_DIRNAME
        self.master = DecisionLedger(self.master_dir)
        self._open: dict[str, DecisionLedger] = {}

    # ── batch lifecycle ─────────────────────────────────────────────────────

    def open_batch(self, batch_id: str, user_id: str, n_docs: int) -> DecisionLedger:
        """Idempotent: a second open of the same batch returns the SAME ledger
        instance and appends nothing — one chain, one seq counter per batch."""
        if batch_id in self._open:
            return self._open[batch_id]
        batch_dir = self.batches_dir / batch_id
        ledger = DecisionLedger(batch_dir)
        self._open[batch_id] = ledger
        ledger.append("batch_started", batch_id=batch_id, user_id=user_id,
                      n_docs=n_docs)
        self.master.append("batch_opened", batch_id=batch_id, user_id=user_id,
                           n_docs=n_docs,
                           batch_ledger=str(batch_dir / LEDGER_FILENAME))
        return ledger

    def ledger_for(self, batch_id: str) -> DecisionLedger:
        if batch_id not in self._open:
            self._open[batch_id] = DecisionLedger(self.batches_dir / batch_id)
        return self._open[batch_id]

    def seal_batch(self, batch_id: str, summary: dict) -> dict:
        """Write the batch's closing entry, then roll its final head hash and
        file digest up into the master chain. Returns the master entry."""
        ledger = self.ledger_for(batch_id)
        ledger.append("batch_completed", batch_id=batch_id, **summary)
        batch_file = ledger.path
        entry = self.master.append(
            "batch_sealed",
            batch_id=batch_id,
            batch_head_hash=ledger.head_hash,
            batch_entry_count=ledger.entry_count,
            batch_ledger_file=str(batch_file),
            batch_ledger_sha256=_file_sha256(batch_file),
            summary=summary,
        )
        self._open.pop(batch_id, None)
        return entry


# ── two-level verification ──────────────────────────────────────────────────

def verify_all(projects_root: Path | str) -> tuple[bool, list[str]]:
    """Verify master chain, then every sealed batch chain against its
    master rollup entry. Returns (ok, report_lines)."""
    root = Path(projects_root)
    report: list[str] = []
    ok = True

    master_path = root / MASTER_DIRNAME / LEDGER_FILENAME
    m_ok, m_n, m_err = verify_file(master_path)
    report.append(f"master: {'OK' if m_ok else 'BROKEN'} "
                  f"({m_n} entries{'' if m_ok else ' — ' + str(m_err)})")
    if not m_ok:
        return False, report

    seals: dict[str, dict] = {}
    with master_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e.get("event") == "batch_sealed":
                seals[e["batch_id"]] = e

    for batch_id, seal in sorted(seals.items()):
        b_path = Path(seal["batch_ledger_file"])
        if not b_path.is_absolute():
            b_path = root.parent / b_path
        b_ok, b_n, b_err = verify_file(b_path)
        if not b_ok:
            ok = False
            report.append(f"  {batch_id}: BROKEN chain ({b_err})")
            continue
        # recompute head + file digest, compare with the master seal
        head = None
        with b_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    head = json.loads(line).get("entry_hash")
        head_ok = head == seal["batch_head_hash"]
        file_ok = _file_sha256(b_path) == seal["batch_ledger_sha256"]
        count_ok = b_n == seal["batch_entry_count"]
        if head_ok and file_ok and count_ok:
            report.append(f"  {batch_id}: OK ({b_n} entries, head+digest match master)")
        else:
            ok = False
            report.append(f"  {batch_id}: MISMATCH vs master "
                          f"(head={head_ok} digest={file_ok} count={count_ok})")
    if not seals:
        report.append("  (no sealed batches)")
    return ok, report


if __name__ == "__main__":
    import sys
    root = sys.argv[2] if len(sys.argv) > 2 else "projects"
    if len(sys.argv) < 2 or sys.argv[1] != "verify-all":
        print("usage: python batch_ledger.py verify-all [projects_root]")
        sys.exit(64)
    ok, lines = verify_all(root)
    print("\n".join(lines))
    sys.exit(0 if ok else 1)
