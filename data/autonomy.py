"""
autonomy.py — earned autonomy for PrefectOS.

Autonomy is not configured; it is earned. Each (client_id, doc_type) pair
starts at tier T0 (everything a human sees) and climbs tiers only as the
decision ledger accumulates evidence that automated verdicts, when audited
by humans, were right. A single human override drops the pair back down.

Tiers
-----
  T0  supervised   : every document goes to a human approver.
  T1  assisted     : system may auto-clear docs with zero findings,
                     up to tier amount ceiling; all else escalates.
  T2  trusted      : system may auto-clear zero-finding docs up to a
                     higher ceiling and minor-finding docs below a
                     small ceiling.
  T3  autonomous   : auto-clear within the client's full policy band;
                     only hard failures and register mismatches escalate.

Promotion requires BOTH volume and accuracy over a rolling window:
    T0->T1 :  >= 50 human-confirmed decisions, accuracy >= 0.98
    T1->T2 :  >= 200 confirmed,               accuracy >= 0.99
    T2->T3 :  >= 1000 confirmed,              accuracy >= 0.995
Demotion: any human override (human reverses an auto-approved doc)
drops one tier immediately; two overrides in a window drop to T0.

Every promotion/demotion is appended to the decision ledger as an
`autonomy_tier_change` event, so the autonomy history is itself
tamper-evident and auditable.

Client policy caps (clients.json) always win: a client may pin
`"max_autonomy_tier": 1` and the pair can never climb past T1
regardless of track record. Absence of config means cap T2 —
T3 must be an explicit, signed-off client choice.

Stdlib only, same design constraints as decision_ledger.py:
a failure here must never break the pipeline — on any error the
answer is the safe one: escalate to a human.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("autonomy")

# ---------------------------------------------------------------- tiers

TIERS = (0, 1, 2, 3)
DEFAULT_MAX_TIER = 2          # T3 only by explicit client sign-off
ROLLING_WINDOW = 2000         # decisions considered for the score

PROMOTION_RULES = {
    # tier -> (min confirmed decisions in window, min accuracy)
    1: (50, 0.98),
    2: (200, 0.99),
    3: (1000, 0.995),
}

# amount ceilings (INR) per tier for zero-finding auto-clear;
# None = client's full policy band applies
TIER_CEILING = {0: 0.0, 1: 2_500_000.0, 2: 10_000_000.0, 3: None}
MINOR_FINDING_CEILING_T2 = 1_000_000.0


@dataclass
class TrackRecord:
    confirmed: int = 0        # auto/AI verdicts a human later confirmed
    overridden: int = 0       # auto/AI verdicts a human reversed
    window: list = field(default_factory=list)  # rolling 1/0 outcomes

    @property
    def accuracy(self) -> float:
        if not self.window:
            return 0.0
        return sum(self.window) / len(self.window)

    def observe(self, correct: bool) -> None:
        self.window.append(1 if correct else 0)
        if len(self.window) > ROLLING_WINDOW:
            self.window = self.window[-ROLLING_WINDOW:]
        if correct:
            self.confirmed += 1
        else:
            self.overridden += 1


# ---------------------------------------------------------------- store

class AutonomyStore:
    """Persistent tier + track-record state per (client_id, doc_type).

    JSON file, atomic-ish writes, thread-safe within one process —
    matching the data/*.json conventions already used by server.py.
    """

    def __init__(self, path: Path | str = "data/autonomy.json") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._state: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(client_id: str, doc_type: str) -> str:
        return f"{client_id}::{doc_type}"

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._state = json.loads(self.path.read_text("utf-8"))
        except Exception:                                  # noqa: BLE001
            log.exception("autonomy state unreadable; starting at T0")
            self._state = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=1), "utf-8")
            tmp.replace(self.path)
        except Exception:                                  # noqa: BLE001
            log.exception("autonomy state save failed (non-fatal)")

    # -- public ----------------------------------------------------

    def tier(self, client_id: str, doc_type: str) -> int:
        entry = self._state.get(self._key(client_id, doc_type))
        return int(entry.get("tier", 0)) if entry else 0

    def record(self, client_id: str, doc_type: str) -> TrackRecord:
        entry = self._state.get(self._key(client_id, doc_type)) or {}
        tr = TrackRecord()
        tr.confirmed = int(entry.get("confirmed", 0))
        tr.overridden = int(entry.get("overridden", 0))
        tr.window = list(entry.get("window", []))
        return tr

    def observe_human_verdict(
        self,
        client_id: str,
        doc_type: str,
        *,
        ai_verdict_correct: bool,
        max_tier: int = DEFAULT_MAX_TIER,
        approver: str = "",
    ) -> tuple[int, int]:
        """Feed one human review outcome; returns (old_tier, new_tier).

        Call this whenever a human confirms or overrides a system
        verdict. Tier changes are decided here and, if any, appended
        to the active decision ledger by the caller via ledger_event().
        """
        with self._lock:
            key = self._key(client_id, doc_type)
            entry = self._state.setdefault(
                key, {"tier": 0, "confirmed": 0, "overridden": 0, "window": []}
            )
            tr = TrackRecord()
            tr.confirmed = entry["confirmed"]
            tr.overridden = entry["overridden"]
            tr.window = entry["window"]
            tr.observe(ai_verdict_correct)

            old = int(entry["tier"])
            new = self._next_tier(old, tr, ai_verdict_correct, max_tier)

            entry.update(
                tier=new,
                confirmed=tr.confirmed,
                overridden=tr.overridden,
                window=tr.window,
                last_review=datetime.now(timezone.utc).isoformat(),
                last_approver=approver,
            )
            self._save()
            if new != old:
                log.info("autonomy %s: T%d -> T%d", key, old, new)
            return old, new

    @staticmethod
    def _next_tier(current: int, tr: TrackRecord,
                   last_correct: bool, max_tier: int) -> int:
        # demotion first — overrides are expensive by design
        if not last_correct:
            recent_overrides = tr.window[-ROLLING_WINDOW:].count(0)
            return 0 if recent_overrides >= 2 else max(0, current - 1)
        # promotion: climb at most one tier per review
        candidate = current + 1
        if candidate > min(max_tier, max(TIERS)):
            return current
        need_n, need_acc = PROMOTION_RULES.get(candidate, (10**9, 1.1))
        n = len(tr.window)
        if n >= need_n and tr.accuracy >= need_acc:
            return candidate
        return current


# ---------------------------------------------------------------- gate

@dataclass(frozen=True)
class AutonomyDecision:
    allowed: bool
    tier: int
    reason: str


def may_auto_clear(
    store: AutonomyStore,
    *,
    client_id: str,
    doc_type: str,
    amount_inr: float | None,
    findings: str,               # "none" | "minor" | "major"
    client_policy: dict | None = None,
) -> AutonomyDecision:
    """The one question the pipeline asks before auto-clearing a doc.

    `findings` comes from the deterministic pass:
      none  = all checks passed
      minor = discrepancies within tolerance (formatting, rounding)
      major = rule failures, register mismatch, missing fields

    On any internal error the function returns allowed=False —
    the safe direction is always the human queue.
    """
    try:
        cap = DEFAULT_MAX_TIER
        if client_policy and "max_autonomy_tier" in client_policy:
            cap = int(client_policy["max_autonomy_tier"])
        tier = min(store.tier(client_id, doc_type), cap)

        if findings == "major":
            return AutonomyDecision(False, tier, "major findings always escalate")
        if tier <= 0:
            return AutonomyDecision(False, tier, "tier T0: supervised")
        if findings == "minor":
            if tier >= 2 and amount_inr is not None \
               and amount_inr <= MINOR_FINDING_CEILING_T2:
                return AutonomyDecision(True, tier,
                                        "T2+: minor findings under ceiling")
            return AutonomyDecision(False, tier,
                                    "minor findings below trust threshold")
        # findings == "none"
        ceiling = TIER_CEILING.get(tier)
        if ceiling is None:
            return AutonomyDecision(True, tier, "T3: within policy band")
        if amount_inr is not None and amount_inr > ceiling:
            return AutonomyDecision(False, tier,
                                    f"amount exceeds T{tier} ceiling")
        return AutonomyDecision(True, tier, f"clean doc within T{tier} ceiling")
    except Exception:                                      # noqa: BLE001
        log.exception("autonomy gate error; escalating")
        return AutonomyDecision(False, 0, "gate error: fail safe")


def ledger_event(old_tier: int, new_tier: int, *,
                 client_id: str, doc_type: str, approver: str) -> None:
    """Append a tier change to the active decision ledger (best-effort)."""
    if old_tier == new_tier:
        return
    try:
        from decision_ledger import record
        record(
            "autonomy_tier_change",
            client_id=client_id,
            doc_type=doc_type,
            old_tier=old_tier,
            new_tier=new_tier,
            approver=approver,
            direction="promotion" if new_tier > old_tier else "demotion",
        )
    except Exception:                                      # noqa: BLE001
        log.exception("autonomy ledger event failed (non-fatal)")
