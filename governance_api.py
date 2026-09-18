# Part of the PrefectOS core package — governance observability API.
"""REST surface over the agent-governance layer, for the UI and for ops.

    GET  /governance/agents          autonomy + policy summary per agent
    GET  /governance/receipts?n=50   latest signed receipts (newest first)
    GET  /governance/verify          chain + signature verification
    POST /governance/freeze          circuit breaker (body: agent_id|null, by)
    POST /governance/release         release the breaker
    POST /governance/replay          rehearse a proposed policy (body = policy JSON)
    GET  /governance/shadow-report   agent census + would-have-denied

Wire into batch_api.py:
    from governance_api import router as governance_router
    app.include_router(governance_router)
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from agent_governance import (
    Governor, LEVEL_NAMES, POLICY_PATH, STATE_DIR,
    SignedReceiptLedger, replay_policy, shadow_report,
)

router = APIRouter(prefix="/governance", tags=["governance"])


def _gov() -> Governor:
    if not Path(POLICY_PATH).exists():
        raise HTTPException(404, "no agent policy configured")
    return Governor.load()


@router.get("/agents")
def agents():
    gov = _gov()
    domains = gov.packs.agent_domains() if getattr(gov, "packs", None) else {}
    out = []
    for aid, pol in gov.engine.policies.items():
        a = gov.tracker._agent(aid)
        out.append({
            "agent_id": aid,
            "domain": domains.get(aid, "core"),
            "level": a["level"], "level_name": LEVEL_NAMES[a["level"]],
            "approved": a["approved"], "rejected": a["rejected"],
            "incidents": a["incidents"], "streak": a["streak"],
            "frozen": gov.breaker.is_frozen(aid),
            "always_gate": pol.always_gate,
            "allow_rules": len(pol.allow),
        })
    return {"shadow_mode": gov.shadow,
            "all_frozen": gov.breaker.state["all_frozen"], "agents": out}


@router.get("/packs")
def packs():
    """Industry policy packs — the Agent OS catalog."""
    gov = _gov()
    return {"packs": gov.packs.available()}


@router.post("/packs/{name}/activate")
def activate_pack(name: str, by: str = Body("ops", embed=True)):
    gov = _gov()
    if name not in gov.packs.available():
        raise HTTPException(404, f"unknown pack: {name}")
    gov.packs.set_active(name, True)
    rec = gov.ledger.record("pack_activated", pack=name, by=by)
    return {"pack": name, "active": True, "receipt": rec["receipt_id"]}


@router.post("/packs/{name}/deactivate")
def deactivate_pack(name: str, by: str = Body("ops", embed=True)):
    gov = _gov()
    gov.packs.set_active(name, False)
    rec = gov.ledger.record("pack_deactivated", pack=name, by=by)
    return {"pack": name, "active": False, "receipt": rec["receipt_id"]}


@router.get("/receipts")
def receipts(n: int = 50):
    path = STATE_DIR / "receipts.jsonl"
    if not path.exists():
        return {"receipts": []}
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    return {"receipts": [json.loads(l) for l in lines[-n:]][::-1]}


@router.get("/verify")
def verify():
    path = STATE_DIR / "receipts.jsonl"
    if not path.exists():
        return {"valid": True, "detail": "no receipts yet"}
    ok, detail = SignedReceiptLedger(path).verify()
    return {"valid": ok, "detail": detail}


@router.post("/freeze")
def freeze(agent_id: str | None = Body(None), by: str = Body("ops")):
    rec = _gov().freeze(agent_id, by=by)
    return {"frozen": agent_id or "ALL_AGENTS", "receipt": rec["receipt_id"]}


@router.post("/release")
def release(agent_id: str | None = Body(None), by: str = Body("ops")):
    rec = _gov().unfreeze(agent_id, by=by)
    return {"released": agent_id or "ALL_AGENTS", "receipt": rec["receipt_id"]}


@router.post("/replay")
def replay(policy: dict = Body(...)):
    tmp = STATE_DIR / "_replay_policy.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(policy))
    try:
        return replay_policy(tmp, STATE_DIR / "receipts.jsonl")
    finally:
        tmp.unlink(missing_ok=True)


@router.get("/shadow-report")
def shadow():
    return shadow_report(STATE_DIR / "receipts.jsonl")
