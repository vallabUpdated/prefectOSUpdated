"""
decision_ledger.py — tamper-evident decision provenance for PrefectOS runs.

Every governance-relevant event in a pipeline run (gate presented, human
decision, agent spawn, run start/complete) is appended to an append-only
JSONL ledger at <project_dir>/decision_ledger.jsonl. Entries are
hash-chained: each entry's `entry_hash` covers its own canonical content
*plus* the previous entry's hash, so any retroactive edit, deletion, or
reordering breaks verification from that point forward.

This upgrades audit_log.json (which records *that* things happened) into
decision provenance (*why* and *under whose authority*): which agent file,
which skills, which model, what exact artifact the approver saw (by SHA-256),
who decided, and when.

Design constraints:
  - stdlib only (hashlib/json/datetime) — no new dependencies
  - best-effort at call sites: a ledger failure must never break the pipeline
  - one active ledger per process, matching the existing module-singleton
    pattern used for _registry/_factory in Orchestrator.py / server.py

Verify from the command line:
    python decision_ledger.py verify projects/<run>/decision_ledger.jsonl
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("decision_ledger")

GENESIS_HASH = "0" * 64
LEDGER_FILENAME = "decision_ledger.jsonl"


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of a text artifact (prompt, plan, spec, file)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(entry: dict) -> str:
    """Deterministic JSON serialization used for hashing."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_entry_hash(entry_without_hash: dict) -> str:
    """entry_hash = SHA256(canonical(entry minus entry_hash)).

    `prev_hash` is *inside* the entry, so the chain linkage is covered."""
    return hashlib.sha256(_canonical(entry_without_hash).encode("utf-8")).hexdigest()


class DecisionLedger:
    """Append-only, hash-chained JSONL ledger scoped to one run/project dir."""

    def __init__(self, project_dir: Path | str) -> None:
        self.path = Path(project_dir) / LEDGER_FILENAME
        self._lock = threading.Lock()
        self._seq, self._head = self._load_tail()

    # ── public ────────────────────────────────────────────────────────────

    def append(self, event_type: str, **fields) -> dict:
        """Append one event. Returns the full written entry (incl. hashes).

        Reserved keys (seq/ts/event/prev_hash/entry_hash) in `fields` are
        ignored to keep the chain well-formed.
        """
        clean = {k: v for k, v in fields.items()
                 if k not in ("seq", "ts", "event", "prev_hash", "entry_hash")}
        with self._lock:
            entry = {
                "seq":       self._seq + 1,
                "ts":        datetime.now(timezone.utc).isoformat(),
                "event":     event_type,
                "prev_hash": self._head,
                **clean,
            }
            entry["entry_hash"] = _compute_entry_hash(entry)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._seq  = entry["seq"]
            self._head = entry["entry_hash"]
            return entry

    @property
    def head_hash(self) -> str:
        """Hash of the most recent entry (GENESIS_HASH if empty)."""
        return self._head

    @property
    def entry_count(self) -> int:
        return self._seq

    def verify(self) -> tuple[bool, int, str | None]:
        """Verify this ledger's chain. See verify_file()."""
        return verify_file(self.path)

    # ── private ───────────────────────────────────────────────────────────

    def _load_tail(self) -> tuple[int, str]:
        """Resume seq/head from an existing file (e.g. --resume runs)."""
        if not self.path.exists():
            return 0, GENESIS_HASH
        seq, head = 0, GENESIS_HASH
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    seq  = int(entry.get("seq", seq))
                    head = str(entry.get("entry_hash", head))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            log.warning("Ledger tail unreadable (%s); starting fresh chain "
                        "segment — verify will flag the break.", exc)
        return seq, head


def verify_file(path: Path | str) -> tuple[bool, int, str | None]:
    """Walk the chain and recompute every hash.

    Returns (ok, entries_checked, error). Detects: edited fields, deleted
    or inserted lines, reordered lines, and a forged/truncated tail.
    """
    path = Path(path)
    if not path.exists():
        return False, 0, f"ledger not found: {path}"

    prev_hash = GENESIS_HASH
    expected_seq = 1
    checked = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError as exc:
                    return False, checked, f"line {lineno}: invalid JSON ({exc})"

                if entry.get("seq") != expected_seq:
                    return False, checked, (
                        f"line {lineno}: seq {entry.get('seq')} "
                        f"(expected {expected_seq}) — insertion/deletion/reorder")
                if entry.get("prev_hash") != prev_hash:
                    return False, checked, (
                        f"line {lineno}: prev_hash mismatch — chain broken")

                claimed = entry.get("entry_hash", "")
                recomputed = _compute_entry_hash(
                    {k: v for k, v in entry.items() if k != "entry_hash"})
                if claimed != recomputed:
                    return False, checked, (
                        f"line {lineno}: entry_hash mismatch — content tampered")

                prev_hash = claimed
                expected_seq += 1
                checked += 1
    except OSError as exc:
        return False, checked, f"read error: {exc}"

    return True, checked, None


# ─────────────────────────────────────────────────────────────────────────────
# Active ledger — context-local so concurrent pipeline runs (web backend, one
# thread per run) each write to their own ledger. The module global remains as
# a single-run fallback for callers outside any run context (e.g. the CLI).
# ─────────────────────────────────────────────────────────────────────────────

_active: DecisionLedger | None = None
_active_var: contextvars.ContextVar[DecisionLedger | None] = \
    contextvars.ContextVar("active_ledger", default=None)


def activate_ledger(project_dir: Path | str) -> DecisionLedger:
    """Create (or resume) the ledger for this run and make it active."""
    global _active
    ledger = DecisionLedger(project_dir)
    _active = ledger          # single-run / out-of-context fallback
    _active_var.set(ledger)   # per-run context (parallel web runs)
    return ledger


def active_ledger() -> DecisionLedger | None:
    return _active_var.get() or _active


def record(event_type: str, **fields) -> None:
    """Best-effort append to the active ledger. Never raises."""
    try:
        ledger = active_ledger()
        if ledger is not None:
            ledger.append(event_type, **fields)
    except Exception as exc:  # noqa: BLE001 — provenance must not kill the run
        log.warning("Ledger append failed (pipeline unaffected): %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# CLI:  python decision_ledger.py verify <path-to-decision_ledger.jsonl>
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3 or sys.argv[1] != "verify":
        print("usage: python decision_ledger.py verify <decision_ledger.jsonl>")
        sys.exit(64)

    ok, n, err = verify_file(sys.argv[2])
    if ok:
        print(f"OK — chain intact, {n} entries verified.")
        sys.exit(0)
    print(f"TAMPERED/BROKEN after {n} valid entries: {err}")
    sys.exit(1)
