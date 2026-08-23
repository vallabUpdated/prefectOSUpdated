"""Replayable event log for a pipeline run.

The web layer streams a run's progress to the dashboard over SSE. Historically
every run owned a single ``queue.Queue``: ``/stream/<run_id>`` *popped* from it,
so events were consumed exactly once and vanished. That made the orchestrator
window a "you had to be there" view — a reload, a second browser window, or
opening the orchestrator after a run started elsewhere showed an empty log and
no stage progress, even while the pipeline was still running.

``RunEventStore`` replaces that queue with an append-only log:

* every event gets a monotonic ``seq`` (1-based) and is kept in memory,
* it is also appended to ``<project_dir>/events.jsonl`` once the store is bound
  to a project directory, so a run can be replayed after the server restarts,
* any number of subscribers can attach at once; each gets its own queue seeded
  with the backlog it missed, then live events, with no gaps and no duplicates.

The seq doubles as the SSE ``id:`` field, so a browser reconnect carries
``Last-Event-ID`` and resumes exactly where it left off.

Nothing here knows about Flask or the pipeline — it is a plain in-process
pub/sub log, safe to call from the pipeline thread and from request threads.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path

log = logging.getLogger("server.events")

EVENTS_FILENAME = "events.jsonl"

# Safety valve: a runaway run cannot pin unbounded memory. The on-disk log
# keeps everything; only the in-memory replay buffer is trimmed.
MAX_MEMORY_EVENTS = 50_000


class RunEventStore:
    """Append-only, replayable, multi-subscriber event log for one run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._lock = threading.Lock()
        self._wlock = threading.Lock()   # serialises appends to events.jsonl
        self._seq = 0
        self._history: list[dict] = []
        self._subs: set[queue.Queue] = set()
        self._path: Path | None = None
        self._persisted = 0          # events already written to disk
        self._trimmed = 0            # events dropped from the memory buffer

    # ── writing ──────────────────────────────────────────────────────────────

    def bind(self, project_dir: str | Path) -> None:
        """Point the store at a project directory and flush the backlog to it.

        Called once the run's project dir exists. Events emitted before the
        bind (there are usually none) are written out at this moment, so the
        on-disk log always starts at seq 1.
        """
        with self._lock:
            self._path = Path(project_dir) / EVENTS_FILENAME
            backlog = self._history[self._persidx():]
        self._append_to_disk(backlog)

    def emit(self, data: dict) -> dict:
        """Record an event, fan it out to subscribers, return it (with ``seq``)."""
        with self._lock:
            self._seq += 1
            data["seq"] = self._seq
            self._history.append(data)
            if len(self._history) > MAX_MEMORY_EVENTS:
                drop = len(self._history) - MAX_MEMORY_EVENTS
                del self._history[:drop]
                self._trimmed += drop
            subs = list(self._subs)
        for q in subs:
            q.put(data)
        self._append_to_disk([data])
        return data

    def _persidx(self) -> int:
        """Index into ``_history`` of the first not-yet-persisted event."""
        return max(0, self._persisted - self._trimmed)

    def _append_to_disk(self, events: list[dict]) -> None:
        if not events or self._path is None:
            return
        with self._wlock:
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    for ev in events:
                        fh.write(json.dumps(ev, default=str) + "\n")
                self._persisted = max(self._persisted, events[-1].get("seq", self._persisted))
            except Exception as exc:                                # noqa: BLE001
                # Persistence is best-effort: a full disk must never kill a run.
                log.warning("events.jsonl append failed for %s: %s", self.run_id, exc)

    # ── reading ──────────────────────────────────────────────────────────────

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def history_after(self, after_seq: int = 0) -> list[dict]:
        """Every recorded event with ``seq`` > ``after_seq`` (memory buffer)."""
        with self._lock:
            return [e for e in self._history if e.get("seq", 0) > after_seq]

    def subscribe(self, after_seq: int = 0) -> queue.Queue:
        """Attach a subscriber, pre-seeded with the backlog it missed.

        The backlog copy and the registration happen under one lock, so an
        event emitted concurrently lands either in the backlog or in the queue
        — never in both, never in neither.
        """
        q: queue.Queue = queue.Queue()
        with self._lock:
            for ev in self._history:
                if ev.get("seq", 0) > after_seq:
                    q.put(ev)
            self._subs.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._subs.discard(q)


def replay_from_disk(project_dir: str | Path, after_seq: int = 0) -> list[dict]:
    """Read a finished run's persisted events back (for a past-run replay).

    Returns an empty list when the run predates event persistence or the file
    is unreadable. Malformed lines are skipped rather than failing the replay.
    """
    path = Path(project_dir) / EVENTS_FILENAME
    if not path.is_file():
        return []
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("seq", 0) > after_seq:
                    events.append(ev)
    except Exception as exc:                                        # noqa: BLE001
        log.warning("events.jsonl replay failed for %s: %s", project_dir, exc)
        return events
    return events
