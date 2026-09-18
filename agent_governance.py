# Part of the PrefectOS core package — agent governance layer.
"""Deny-by-default policy, signed receipts, and earned autonomy for agents.

Three capabilities, matching the emerging agentic-governance standard
(deny-by-default enforcement outside the model, HITL approval, signed
audit, autonomy that is earned — cf. CSA Agentic Trust Framework):

1. **PolicyEngine** — deterministic, deny-by-default authorization for
   every agent tool/model call. Anything not explicitly allowed in
   agent_policy.json is DENIED before execution. No LLM in the
   enforcement path: same agent, same action, same decision, every time.

2. **SignedReceiptLedger** — every governance decision and agent action
   is sealed as a *receipt*: hash-chained (tamper-evident, as the
   existing ledgers) AND HMAC-SHA256 signed with a key held outside the
   codebase (PREFECTOS_SIGNING_KEY env). The chain proves order and
   integrity; the signature proves the platform — not a later editor —
   wrote each record.

3. **AutonomyTracker** — per-agent trust levels with promotion earned
   by track record and demotion on incident:
       L1 OBSERVE    agent may only propose; humans do everything
       L2 APPROVE    agent acts, human approves EVERY action (default)
       L3 NOTIFY     agent acts, human notified post-action
       L4 AUTONOMOUS periodic review only
   Promotion requires a minimum number of consecutively approved
   actions with zero incidents; ANY incident demotes to L1 immediately.
   New agents start at L2, never higher.

Usage (wrap any tool/model call site — e.g. in Orchestrator stages):

    gov = Governor.load()
    decision = gov.authorize(agent_id="spec_writer", action="tool:write_file",
                             resource="project_output/spec.md")
    if decision.allowed and decision.needs_approval:
        ...queue for human gate; then gov.record_outcome(receipt_id, "approved")
    elif decision.allowed:
        ...execute; gov.record_outcome(receipt_id, "executed")
    # denied calls never execute; the denial is already receipted.

Verify everything:  python agent_governance.py --verify
Inspect an agent:   python agent_governance.py --status spec_writer
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATE_DIR = Path(os.getenv("AGENT_GOV_STATE", "project_output/agent_governance"))
POLICY_PATH = Path(os.getenv("AGENT_POLICY", "agent_policy.json"))
PACKS_DIR = Path(os.getenv("AGENT_PACKS", "policy_packs"))

L1_OBSERVE, L2_APPROVE, L3_NOTIFY, L4_AUTONOMOUS = 1, 2, 3, 4
LEVEL_NAMES = {1: "OBSERVE", 2: "APPROVE", 3: "NOTIFY", 4: "AUTONOMOUS"}


def _signing_key() -> bytes:
    key = os.environ.get("PREFECTOS_SIGNING_KEY", "")
    if not key:
        raise RuntimeError(
            "PREFECTOS_SIGNING_KEY not set — signed receipts require a key. "
            "Generate one (e.g. `openssl rand -hex 32`) and put it in "
            "/etc/prefectos/env; never in code or config."
        )
    return key.encode()


# ── Signed receipts: hash chain + HMAC per record ──────────────────────
class SignedReceiptLedger:
    """Hash chain proves order + integrity; HMAC proves authorship."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        last = ""
        with self.path.open() as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last)["record_hash"] if last else "GENESIS"

    def record(self, event: str, **fields) -> dict:
        rec = {
            "receipt_id": uuid.uuid4().hex[:12],
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event, **fields,
            "prev_hash": self._prev,
        }
        body = json.dumps(rec, sort_keys=True).encode()
        rec["record_hash"] = hashlib.sha256(body).hexdigest()
        rec["signature"] = hmac.new(_signing_key(), body, hashlib.sha256).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self._prev = rec["record_hash"]
        return rec

    def verify(self) -> tuple[bool, str]:
        prev, key = "GENESIS", _signing_key()
        with self.path.open() as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                sig = rec.pop("signature")
                claimed = rec.pop("record_hash")
                if rec.get("prev_hash") != prev:
                    return False, f"chain break at line {n}"
                body = json.dumps(rec, sort_keys=True).encode()
                if hashlib.sha256(body).hexdigest() != claimed:
                    return False, f"hash mismatch at line {n}"
                if not hmac.compare_digest(
                        sig, hmac.new(key, body, hashlib.sha256).hexdigest()):
                    return False, f"signature invalid at line {n} (wrong key or forged)"
                prev = claimed
        return True, "ok"


# ── Deny-by-default policy ─────────────────────────────────────────────
@dataclass
class AgentPolicy:
    """One agent's allowlist. `allow` entries are "action" or
    "action::resource_glob" — anything else is denied."""
    agent_id: str
    allow: list[str] = field(default_factory=list)
    max_calls_per_run: int = 200
    always_gate: list[str] = field(default_factory=list)  # approval even at L3/L4

    def permits(self, action: str, resource: str) -> bool:
        for rule in self.allow:
            if "::" in rule:
                act, pat = rule.split("::", 1)
                if fnmatch.fnmatch(action, act) and fnmatch.fnmatch(resource, pat):
                    return True
            elif fnmatch.fnmatch(action, rule):
                return True
        return False

    def force_gated(self, action: str) -> bool:
        return any(fnmatch.fnmatch(action, r) for r in self.always_gate)


class PolicyEngine:
    def __init__(self, policies: dict[str, AgentPolicy]):
        self.policies = policies

    @classmethod
    def load(cls, path: Path = POLICY_PATH) -> "PolicyEngine":
        raw = json.loads(Path(path).read_text())
        return cls({a["agent_id"]: AgentPolicy(**a) for a in raw.get("agents", [])})

    def check(self, agent_id: str, action: str, resource: str) -> tuple[bool, str]:
        pol = self.policies.get(agent_id)
        if pol is None:
            return False, "unknown_agent"          # deny-by-default: no policy, no calls
        if not pol.permits(action, resource):
            return False, "not_in_allowlist"
        return True, "ok"


# ── Earned autonomy ────────────────────────────────────────────────────
class AutonomyTracker:
    """Trust is earned per agent and lost instantly on incident."""

    PROMOTE_AFTER = {L2_APPROVE: 25, L3_NOTIFY: 100}   # approved actions to next level
    START_LEVEL = L2_APPROVE

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict = json.loads(path.read_text()) if path.exists() else {}

    def _agent(self, agent_id: str) -> dict:
        return self.state.setdefault(agent_id, {
            "level": self.START_LEVEL, "streak": 0,
            "approved": 0, "rejected": 0, "incidents": 0,
        })

    def level(self, agent_id: str) -> int:
        return self._agent(agent_id)["level"]

    def note_approved(self, agent_id: str) -> tuple[int, bool]:
        a = self._agent(agent_id)
        a["approved"] += 1
        a["streak"] += 1
        promoted = False
        need = self.PROMOTE_AFTER.get(a["level"])
        if need and a["streak"] >= need and a["incidents"] == 0:
            a["level"] += 1
            a["streak"] = 0
            promoted = True
        self._save()
        return a["level"], promoted

    def note_rejected(self, agent_id: str) -> int:
        a = self._agent(agent_id)
        a["rejected"] += 1
        a["streak"] = 0                            # trust streak resets
        self._save()
        return a["level"]

    def note_incident(self, agent_id: str) -> int:
        a = self._agent(agent_id)
        a["incidents"] += 1
        a["level"] = L1_OBSERVE                    # immediate demotion, no appeal
        a["streak"] = 0
        self._save()
        return a["level"]

    def _save(self):
        self.path.write_text(json.dumps(self.state, indent=2))


# ── Governor: the one object call sites talk to ────────────────────────
@dataclass
class Decision:
    allowed: bool
    needs_approval: bool
    reason: str
    level: int
    receipt_id: str


class CircuitBreaker:
    """Emergency stop: freeze one agent or all of them. The freeze and
    the release are themselves receipted — even the brake is auditable."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = json.loads(path.read_text()) if path.exists() else \
            {"all_frozen": False, "agents": {}}

    def is_frozen(self, agent_id: str) -> bool:
        return self.state["all_frozen"] or \
            self.state["agents"].get(agent_id, False)

    def set(self, frozen: bool, agent_id: str | None = None):
        if agent_id is None:
            self.state["all_frozen"] = frozen
        else:
            self.state["agents"][agent_id] = frozen
        self.path.write_text(json.dumps(self.state, indent=2))


class PackRegistry:
    """Industry policy packs — the Agent OS layer. Each pack is a JSON file
    (domain, label, agents[]) in policy_packs/. Active packs merge into one
    PolicyEngine; activation/deactivation is receipted like everything else.
    The base agent_policy.json remains always-on for backward compatibility."""

    def __init__(self, packs_dir: Path = PACKS_DIR,
                 state_dir: Path = STATE_DIR):
        self.dir = Path(packs_dir)
        self.state_path = Path(state_dir) / "active_packs.json"
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.active: list[str] = json.loads(self.state_path.read_text()) \
            if self.state_path.exists() else []

    def available(self) -> dict[str, dict]:
        out = {}
        if self.dir.exists():
            for f in sorted(self.dir.glob("*.json")):
                try:
                    d = json.loads(f.read_text())
                    out[f.stem] = {"domain": d.get("domain", f.stem),
                                   "label": d.get("label", f.stem),
                                   "icon": d.get("icon", ""),
                                   "description": d.get("description", ""),
                                   "agents": [a["agent_id"] for a in d.get("agents", [])],
                                   "active": f.stem in self.active}
                except Exception:
                    continue
        return out

    def set_active(self, name: str, active: bool):
        if active and name not in self.active:
            self.active.append(name)
        if not active and name in self.active:
            self.active.remove(name)
        self.state_path.write_text(json.dumps(self.active))

    def agent_domains(self) -> dict[str, str]:
        m = {}
        for name in self.active:
            f = self.dir / f"{name}.json"
            if f.exists():
                d = json.loads(f.read_text())
                for a in d.get("agents", []):
                    m[a["agent_id"]] = d.get("domain", name)
        return m

    def merged_policies(self, base: dict[str, "AgentPolicy"]) -> dict[str, "AgentPolicy"]:
        merged = dict(base)
        for name in self.active:
            f = self.dir / f"{name}.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text())
            for a in d.get("agents", []):
                merged[a["agent_id"]] = AgentPolicy(**a)
        return merged


class Governor:
    def __init__(self, engine: PolicyEngine, tracker: AutonomyTracker,
                 ledger: SignedReceiptLedger,
                 breaker: CircuitBreaker | None = None,
                 shadow: bool = False):
        self.engine, self.tracker, self.ledger = engine, tracker, ledger
        self.breaker = breaker
        # Shadow mode ("CCTV"): every decision is evaluated and receipted
        # exactly as in enforcement, but NOTHING is blocked or gated.
        # Would-be denials are receipted as shadow_denied so two weeks of
        # observation writes the enforcement policy for you.
        self.shadow = shadow
        self._calls: dict[str, int] = {}

    @classmethod
    def load(cls, policy_path: Path = POLICY_PATH,
             state_dir: Path = STATE_DIR,
             shadow: bool | None = None) -> "Governor":
        if shadow is None:
            shadow = os.environ.get("AGENT_GOV_MODE", "enforce") == "shadow"
        engine = PolicyEngine.load(policy_path)
        packs = PackRegistry(state_dir=state_dir)
        engine.policies = packs.merged_policies(engine.policies)
        gov = cls(engine,
                  AutonomyTracker(Path(state_dir) / "autonomy.json"),
                  SignedReceiptLedger(Path(state_dir) / "receipts.jsonl"),
                  breaker=CircuitBreaker(Path(state_dir) / "breaker.json"),
                  shadow=shadow)
        gov.packs = packs
        return gov

    def authorize(self, agent_id: str, action: str, resource: str = "") -> Decision:
        level = self.tracker.level(agent_id)
        pol = self.engine.policies.get(agent_id)

        # Circuit breaker outranks everything — including shadow mode.
        if self.breaker is not None and self.breaker.is_frozen(agent_id):
            rec = self.ledger.record("call_denied", agent_id=agent_id,
                                     action=action, resource=resource,
                                     reason="circuit_breaker", level=level)
            return Decision(False, False, "circuit_breaker", level,
                            rec["receipt_id"])

        # per-run call budget (defense against runaway loops)
        n = self._calls.get(agent_id, 0) + 1
        self._calls[agent_id] = n
        if pol and n > pol.max_calls_per_run:
            rec = self.ledger.record("call_denied", agent_id=agent_id,
                                     action=action, resource=resource,
                                     reason="call_budget_exceeded", level=level)
            return Decision(False, False, "call_budget_exceeded", level,
                            rec["receipt_id"])

        ok, why = self.engine.check(agent_id, action, resource)
        if not ok:
            if self.shadow:
                rec = self.ledger.record("shadow_denied", agent_id=agent_id,
                                         action=action, resource=resource,
                                         reason=why, level=level)
                return Decision(True, False, "shadow:" + why, level,
                                rec["receipt_id"])
            rec = self.ledger.record("call_denied", agent_id=agent_id,
                                     action=action, resource=resource,
                                     reason=why, level=level)
            return Decision(False, False, why, level, rec["receipt_id"])

        if level == L1_OBSERVE and not self.shadow:
            rec = self.ledger.record("call_denied", agent_id=agent_id,
                                     action=action, resource=resource,
                                     reason="observe_only", level=level)
            return Decision(False, False, "observe_only", level, rec["receipt_id"])

        needs = (level == L2_APPROVE or (pol is not None and pol.force_gated(action))) \
                and not self.shadow
        rec = self.ledger.record(
            "call_gated" if needs else "call_allowed",
            agent_id=agent_id, action=action, resource=resource, level=level)
        return Decision(True, needs, "ok", level, rec["receipt_id"])

    def record_outcome(self, receipt_id: str, outcome: str,
                       agent_id: str, approver: str = "system") -> dict:
        """outcome: approved | rejected | executed | incident"""
        if outcome == "approved":
            level, promoted = self.tracker.note_approved(agent_id)
            extra = {"new_level": level, "promoted": promoted}
            if promoted:
                self.ledger.record("autonomy_promoted", agent_id=agent_id,
                                   to_level=LEVEL_NAMES[level], approver=approver)
        elif outcome == "rejected":
            extra = {"new_level": self.tracker.note_rejected(agent_id)}
        elif outcome == "incident":
            level = self.tracker.note_incident(agent_id)
            extra = {"new_level": level}
            self.ledger.record("autonomy_demoted", agent_id=agent_id,
                               to_level=LEVEL_NAMES[level], approver=approver,
                               reason="incident")
        else:
            extra = {}
        return self.ledger.record("outcome", ref_receipt=receipt_id,
                                  agent_id=agent_id, outcome=outcome,
                                  approver=approver, **extra)


    # -- Circuit breaker -------------------------------------------------
    def freeze(self, agent_id: str | None = None, by: str = "ops") -> dict:
        self.breaker.set(True, agent_id)
        return self.ledger.record("breaker_frozen",
                                  scope=agent_id or "ALL_AGENTS", by=by)

    def unfreeze(self, agent_id: str | None = None, by: str = "ops") -> dict:
        self.breaker.set(False, agent_id)
        return self.ledger.record("breaker_released",
                                  scope=agent_id or "ALL_AGENTS", by=by)


# ── Rehearsal room: replay history against a proposed policy ──────────
def replay_policy(proposed_policy: Path, receipts: Path) -> dict:
    """Simulate a proposed agent_policy.json against past call receipts:
    'this rule change would have blocked N calls — here they are.'
    Nothing is enforced; the report turns policy edits into evidence."""
    engine = PolicyEngine.load(proposed_policy)
    would_block, allowed, total = [], 0, 0
    if receipts.exists():
        with receipts.open() as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("event") not in ("call_allowed", "call_gated",
                                          "call_denied", "shadow_denied"):
                    continue
                total += 1
                ok, why = engine.check(r.get("agent_id", ""),
                                       r.get("action", ""),
                                       r.get("resource", ""))
                if ok:
                    allowed += 1
                else:
                    would_block.append({"ts": r.get("ts"),
                                        "agent_id": r.get("agent_id"),
                                        "action": r.get("action"),
                                        "resource": r.get("resource"),
                                        "reason": why})
    return {"calls_replayed": total, "would_allow": allowed,
            "would_block": len(would_block),
            "blocked_calls": would_block[:200]}


def shadow_report(receipts: Path) -> dict:
    """Summarise a shadow-mode observation window: the agent census and
    what enforcement would have refused."""
    agents, denials = {}, []
    if receipts.exists():
        with receipts.open() as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                aid = r.get("agent_id")
                if not aid:
                    continue
                a = agents.setdefault(aid, {"calls": 0, "actions": {},
                                            "would_be_denied": 0})
                if r["event"] in ("call_allowed", "call_gated",
                                  "shadow_denied", "call_denied"):
                    a["calls"] += 1
                    act = r.get("action", "?")
                    a["actions"][act] = a["actions"].get(act, 0) + 1
                if r["event"] == "shadow_denied":
                    a["would_be_denied"] += 1
                    denials.append({"agent_id": aid, "action": r.get("action"),
                                    "resource": r.get("resource"),
                                    "reason": r.get("reason")})
    return {"agents_observed": len(agents), "census": agents,
            "would_be_denied_total": len(denials),
            "would_be_denied": denials[:200]}


# ── CLI ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="PrefectOS agent governance")
    ap.add_argument("--verify", action="store_true",
                    help="verify receipt chain + signatures")
    ap.add_argument("--status", metavar="AGENT_ID",
                    help="show an agent's autonomy record")
    ap.add_argument("--freeze", nargs="?", const="ALL", metavar="AGENT_ID",
                    help="circuit breaker: freeze one agent (or all)")
    ap.add_argument("--unfreeze", nargs="?", const="ALL", metavar="AGENT_ID")
    ap.add_argument("--replay", metavar="PROPOSED_POLICY.json",
                    help="rehearse a proposed policy against past receipts")
    ap.add_argument("--shadow-report", action="store_true",
                    help="agent census + would-have-denied from shadow mode")
    args = ap.parse_args()

    if args.freeze or args.unfreeze:
        gov = Governor.load()
        tgt = args.freeze or args.unfreeze
        aid = None if tgt == "ALL" else tgt
        rec = gov.freeze(aid) if args.freeze else gov.unfreeze(aid)
        print(json.dumps(rec, indent=2)); raise SystemExit(0)
    if args.replay:
        print(json.dumps(replay_policy(Path(args.replay),
                                       STATE_DIR / "receipts.jsonl"), indent=2))
        raise SystemExit(0)
    if args.shadow_report:
        print(json.dumps(shadow_report(STATE_DIR / "receipts.jsonl"), indent=2))
        raise SystemExit(0)

    if args.verify:
        ok, detail = SignedReceiptLedger(STATE_DIR / "receipts.jsonl").verify()
        print(f"receipts: {'VALID' if ok else 'BROKEN'} ({detail})")
        raise SystemExit(0 if ok else 1)
    if args.status:
        t = AutonomyTracker(STATE_DIR / "autonomy.json")
        a = t._agent(args.status)
        print(json.dumps({**a, "level_name": LEVEL_NAMES[a["level"]]}, indent=2))


if __name__ == "__main__":
    main()
