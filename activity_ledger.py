"""Per-licensee activity ledger — what each API key did, day by day.

One append-only JSONL file per access key, under ledger/activity/. Every record
is a single thing that happened: a sign-in, a document job, a question put to
the policy chat, a pipeline run. Records are never edited or deleted; the file
is the record of the day's work for that key.

The key itself is never stored. Its SHA-256 names the file and its last four
characters identify it in the UI, so a ledger can be attributed to a key
without the ledger becoming a place keys leak from.

This is an operational activity log, deliberately separate from
decision_ledger.py, which hash-chains the *approval decisions* inside one
pipeline run and answers a different question ("was this artefact approved, by
whom, unaltered?"). This one answers "what has this licensee been doing?".
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

log = logging.getLogger("server.activity")

ROOT = Path(__file__).parent / "ledger" / "activity"
_lock = threading.Lock()

# Everything the ledger knows how to record. Anything else is stored as-is
# under "other" rather than dropped — an unrecognised activity is still an
# activity, and losing it would make the record incomplete.
KINDS = {
    "login":          "Signed in",
    "logout":         "Signed out",
    "document_job":   "Document processing",
    "chat":           "Policy question",
    "pipeline_run":   "Pipeline run",
    "approval":       "Approval decision",
    "policy_index":   "Policy pack indexed",
    "other":          "Activity",
}

MAX_RECORDS_RETURNED = 2000


def key_id(api_key: str) -> str:
    """Stable, non-reversible id for an access key."""
    return hashlib.sha256((api_key or "anonymous").encode("utf-8")).hexdigest()[:16]


def _path(kid: str) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT / f"{kid}.jsonl"


def _recent_login(kid: str, now: datetime, minutes: int = 15) -> bool:
    """Has this key already been recorded as signing in, just now?"""
    path = ROOT / f"{kid}.jsonl"
    if not path.is_file():
        return False
    try:
        last_login = ""
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if '"kind": "login"' not in line:
                    continue
                try:
                    last_login = json.loads(line).get("ts", "")
                except json.JSONDecodeError:
                    continue
        if not last_login:
            return False
        delta = now - datetime.fromisoformat(last_login)
        return 0 <= delta.total_seconds() < minutes * 60
    except Exception:                                               # noqa: BLE001
        return False


def record(actor: dict | None, kind: str, summary: str, **details) -> dict | None:
    """Append one activity. Best-effort: never raises into a request path."""
    actor = actor or {}
    api_key = (actor.get("api_key") or "").strip()
    if not api_key:
        # No key, no ledger: an unauthenticated action belongs to nobody, and
        # inventing an owner for it would make the record misleading.
        return None

    now = datetime.now()
    entry = {
        "ts": now.isoformat(timespec="seconds"),
        "day": now.strftime("%Y-%m-%d"),
        "kind": kind if kind in KINDS else "other",
        "summary": summary,
        "user_id": actor.get("user_id") or "",
        "user_name": actor.get("user_name") or "",
        "role": actor.get("role") or "",
        "institution": actor.get("institution") or "",
        "key_last4": api_key[-4:],
        "details": {k: v for k, v in details.items() if v is not None},
    }

    kid = key_id(api_key)

    # A sign-in is one event, but the dashboard can mount the workspace more
    # than once per session (navigating back into it, a remount). Collapse
    # repeats here rather than trusting the client to hold a flag.
    if kind == "login" and _recent_login(kid, now):
        return None

    try:
        with _lock:
            with _path(kid).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:                                        # noqa: BLE001
        log.warning("activity ledger append failed: %s", exc)
        return None
    return entry


def read(api_key: str, day: str = "", kind: str = "") -> list[dict]:
    """Every record for a key, newest first, optionally filtered."""
    path = _path(key_id(api_key))
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if day and e.get("day") != day:
                    continue
                if kind and e.get("kind") != kind:
                    continue
                out.append(e)
    except Exception as exc:                                        # noqa: BLE001
        log.warning("activity ledger read failed: %s", exc)
    out.reverse()
    return out[:MAX_RECORDS_RETURNED]


def _day_totals(records: list[dict]) -> dict:
    tokens = sum(int(r["details"].get("tokens") or 0) for r in records)
    cost = sum(float(r["details"].get("cost_usd") or 0) for r in records)
    docs = sum(int(r["details"].get("documents") or 0) for r in records)
    return {
        "records": len(records),
        "tokens": tokens,
        "cost_usd": round(cost, 6),
        "documents": docs,
        "by_kind": dict(Counter(r["kind"] for r in records)),
    }


def days(api_key: str, kind: str = "") -> dict:
    """Records grouped by day, newest day first, with per-day totals.

    This is the shape the Ledger Records screen renders: a day header with what
    it cost and how much was processed, and the individual records beneath.
    """
    records = read(api_key, kind=kind)
    grouped: dict[str, list[dict]] = {}
    for r in records:
        grouped.setdefault(r.get("day", "unknown"), []).append(r)

    out_days = [{
        "day": day,
        "records": items,
        "totals": _day_totals(items),
    } for day, items in sorted(grouped.items(), reverse=True)]

    who = records[0] if records else {}
    return {
        "days": out_days,
        "totals": _day_totals(records),
        "kinds": KINDS,
        "owner": {
            "user_name": who.get("user_name", ""),
            "role": who.get("role", ""),
            "institution": who.get("institution", ""),
            "key_last4": who.get("key_last4", ""),
        },
    }


def export_lines(api_key: str) -> str:
    """The raw ledger file for this key, for download."""
    path = _path(key_id(api_key))
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except Exception:                                               # noqa: BLE001
        return ""
