# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Agent lifecycle registry: PENDING → ALIVE → TORN_DOWN."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path

from .config import log, MAX_AGENTS

# ─────────────────────────────────────────────────────────────────────────────

class AgentStatus(str, Enum):
    PENDING   = "PENDING"     # registered but not yet spawned
    ALIVE     = "ALIVE"       # spawned, LangChain chain active
    TORN_DOWN = "TORN_DOWN"   # invoke() called, references nulled
    FAILED    = "FAILED"      # exception during invoke()


# ─────────────────────────────────────────────────────────────────────────────
# AgentRecord — one entry per agent in the registry
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AgentRecord:
    agent_id:     str
    slot:         int                        # 1-based spawn order
    model:        str
    stage:        str
    status:       AgentStatus = AgentStatus.PENDING
    spawned_at:   str         = ""
    torn_down_at: str         = ""
    elapsed_s:    float       = 0.0
    output_chars: int         = 0
    error:        str         = ""

    def as_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ─────────────────────────────────────────────────────────────────────────────
# AgentRegistry — visible runtime table of all agents
# ─────────────────────────────────────────────────────────────────────────────

class AgentRegistry:
    """
    Tracks every agent across its full lifecycle.
    Printed as a table after each state change so the user can always
    see which agents exist, which are alive, and which have been destroyed.
    Persisted to projects/<id>/agent_registry.json after every update.
    """

    def __init__(self, project_dir: Path) -> None:
        self._records: list[AgentRecord] = []
        self._project_dir = project_dir
        self._registry_path = project_dir / "agent_registry.json"

    # ── public ──────────────────────────────────────────────────────────────

    def register(self, agent_id: str, slot: int, model: str, stage: str) -> AgentRecord:
        """Add a PENDING record before the agent is spawned."""
        rec = AgentRecord(
            agent_id=agent_id,
            slot=slot,
            model=model,
            stage=stage,
            status=AgentStatus.PENDING,
        )
        self._records.append(rec)
        self._persist()
        self._print_table(f"Agent registered: [{agent_id}]")
        return rec

    def mark_alive(self, agent_id: str) -> None:
        rec = self._get(agent_id)
        rec.status     = AgentStatus.ALIVE
        rec.spawned_at = datetime.now().isoformat(timespec="seconds")
        self._persist()
        self._print_table(f"Agent ALIVE: [{agent_id}]")

    def mark_torn_down(
        self,
        agent_id:     str,
        elapsed_s:    float,
        output_chars: int,
    ) -> None:
        rec = self._get(agent_id)
        rec.status       = AgentStatus.TORN_DOWN
        rec.torn_down_at = datetime.now().isoformat(timespec="seconds")
        rec.elapsed_s    = round(elapsed_s, 2)
        rec.output_chars = output_chars
        self._persist()
        self._print_table(f"Agent TORN DOWN: [{agent_id}]")

    def mark_failed(self, agent_id: str, error: str) -> None:
        rec = self._get(agent_id)
        rec.status = AgentStatus.FAILED
        rec.error  = error
        self._persist()
        self._print_table(f"Agent FAILED: [{agent_id}]")

    def all_records(self) -> list[AgentRecord]:
        return list(self._records)

    def count_by_status(self, status: AgentStatus) -> int:
        return sum(1 for r in self._records if r.status == status)

    # ── private ─────────────────────────────────────────────────────────────

    def _get(self, agent_id: str) -> AgentRecord:
        for r in self._records:
            if r.agent_id == agent_id:
                return r
        raise KeyError(f"No registry entry for agent '{agent_id}'")

    def _persist(self) -> None:
        self._registry_path.write_text(
            json.dumps([r.as_dict() for r in self._records], indent=2),
            encoding="utf-8",
        )

    def _print_table(self, event: str) -> None:
        """Print the full registry as an ASCII table to the terminal."""
        sep   = "─" * 78
        alive = self.count_by_status(AgentStatus.ALIVE)
        total = len(self._records)

        print(f"\n{sep}")
        print(f"  AGENT REGISTRY  [{event}]")
        print(f"  Budget: {total}/{MAX_AGENTS} agents registered  |  {alive} currently ALIVE")
        print(sep)
        print(f"  {'#':<4} {'ID':<18} {'MODEL':<22} {'STAGE':<14} {'STATUS':<12} {'ELAPSED':>8}")
        print(f"  {'─'*4} {'─'*18} {'─'*22} {'─'*14} {'─'*12} {'─'*8}")
        for r in self._records:
            status_icon = {
                AgentStatus.PENDING:   "⏳ PENDING",
                AgentStatus.ALIVE:     "🟢 ALIVE",
                AgentStatus.TORN_DOWN: "⚫ TORN DOWN",
                AgentStatus.FAILED:    "🔴 FAILED",
            }.get(r.status, r.status.value)
            elapsed = f"{r.elapsed_s:.1f}s" if r.elapsed_s else "—"
            print(
                f"  {r.slot:<4} {r.agent_id:<18} {r.model:<22} "
                f"{r.stage:<14} {status_icon:<20} {elapsed:>8}"
            )
        print(sep + "\n")


