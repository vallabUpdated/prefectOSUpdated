# PrefectOS core — aggregate registry for pooled agents.
"""PoolRegistry — additive companion to AgentRegistry (core/registry.py).

AgentRegistry keeps one lifecycle row per ephemeral agent and reprints its
table on every transition — correct for a handful of governed one-shot
agents, a hot lock at 250 docs/sec. PoolRegistry keeps ONE row per pooled
agent role with atomically-updated aggregate counters (calls, in-flight,
tokens, failures), persisted to <project_dir>/agent_pools.json for the SSE
dashboard. AgentRegistry is not imported or modified.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class PoolRecord:
    agent_id: str
    role: str
    model: str
    tier: str
    batch_id: str
    created_at: str = ""
    calls_total: int = 0
    calls_ok: int = 0
    calls_failed: int = 0
    in_flight: int = 0
    fresh_tokens: int = 0
    cached_tokens: int = 0
    total_elapsed_s: float = 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["avg_call_s"] = (round(self.total_elapsed_s / self.calls_total, 2)
                           if self.calls_total else None)
        cache_total = self.fresh_tokens + self.cached_tokens
        d["cache_hit_pct"] = (round(100 * self.cached_tokens / cache_total, 1)
                              if cache_total else None)
        return d


class PoolRegistry:
    def __init__(self, project_dir: Path | str):
        self._path = Path(project_dir) / "agent_pools.json"
        self._records: dict[str, PoolRecord] = {}
        self._lock = threading.Lock()

    def register_pool(self, agent_id: str, role: str, model: str,
                      tier: str, batch_id: str) -> PoolRecord:
        with self._lock:
            rec = PoolRecord(agent_id=agent_id, role=role, model=model,
                             tier=tier, batch_id=batch_id,
                             created_at=datetime.now().isoformat(timespec="seconds"))
            self._records[agent_id] = rec
            self._persist()
            return rec

    def call_started(self, agent_id: str) -> None:
        with self._lock:
            rec = self._records.get(agent_id)
            if rec:
                rec.in_flight += 1
                rec.calls_total += 1
                self._persist()

    def call_finished(self, agent_id: str, ok: bool, elapsed_s: float,
                      fresh_tokens: int = 0, cached_tokens: int = 0) -> None:
        with self._lock:
            rec = self._records.get(agent_id)
            if rec:
                rec.in_flight = max(rec.in_flight - 1, 0)
                rec.calls_ok += 1 if ok else 0
                rec.calls_failed += 0 if ok else 1
                rec.fresh_tokens += fresh_tokens
                rec.cached_tokens += cached_tokens
                rec.total_elapsed_s += elapsed_s
                self._persist()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [r.as_dict() for r in self._records.values()]

    def _persist(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps([r.as_dict() for r in self._records.values()],
                           indent=2), encoding="utf-8")
        except OSError:
            pass                                  # metering must never kill a run
