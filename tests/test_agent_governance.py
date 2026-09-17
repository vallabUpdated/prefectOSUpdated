"""Offline tests: deny-by-default policy, signed receipts, earned autonomy."""
import json, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
os.environ.setdefault("PREFECTOS_SIGNING_KEY", "test-key-not-for-production")

from agent_governance import (  # noqa: E402
    AgentPolicy, AutonomyTracker, Governor, PolicyEngine,
    SignedReceiptLedger, L1_OBSERVE, L2_APPROVE, L3_NOTIFY,
)


def make_gov(tmp_path, level_seed=None):
    eng = PolicyEngine({
        "writer": AgentPolicy("writer",
            allow=["model:complete", "tool:write_file::out/*"],
            max_calls_per_run=5, always_gate=["tool:write_file*"]),
    })
    tr = AutonomyTracker(tmp_path / "autonomy.json")
    if level_seed:
        tr.state["writer"] = level_seed; tr._save()
    return Governor(eng, tr, SignedReceiptLedger(tmp_path / "receipts.jsonl"))


# ── deny-by-default ────────────────────────────────────────────────────
def test_unknown_agent_denied(tmp_path):
    g = make_gov(tmp_path)
    d = g.authorize("rogue", "model:complete")
    assert not d.allowed and d.reason == "unknown_agent"

def test_action_not_in_allowlist_denied(tmp_path):
    g = make_gov(tmp_path)
    d = g.authorize("writer", "tool:delete_file", "out/x")
    assert not d.allowed and d.reason == "not_in_allowlist"

def test_resource_glob_enforced(tmp_path):
    g = make_gov(tmp_path)
    assert g.authorize("writer", "tool:write_file", "out/spec.md").allowed
    d = g.authorize("writer", "tool:write_file", "/etc/passwd")
    assert not d.allowed and d.reason == "not_in_allowlist"

def test_call_budget(tmp_path):
    g = make_gov(tmp_path)
    for _ in range(5):
        assert g.authorize("writer", "model:complete").allowed
    d = g.authorize("writer", "model:complete")
    assert not d.allowed and d.reason == "call_budget_exceeded"

def test_every_denial_is_receipted(tmp_path):
    g = make_gov(tmp_path)
    g.authorize("rogue", "model:complete")
    events = [json.loads(l)["event"] for l in
              (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert events == ["call_denied"]


# ── earned autonomy ────────────────────────────────────────────────────
def test_l2_requires_approval_and_promotes_after_streak(tmp_path):
    g = make_gov(tmp_path)
    assert g.tracker.level("writer") == L2_APPROVE
    d = g.authorize("writer", "model:complete")
    assert d.allowed and d.needs_approval
    for _ in range(AutonomyTracker.PROMOTE_AFTER[L2_APPROVE]):
        g.record_outcome("r", "approved", "writer", approver="sarah")
    assert g.tracker.level("writer") == L3_NOTIFY
    d = g.authorize("writer", "model:complete")
    assert d.allowed and not d.needs_approval          # earned it

def test_always_gate_survives_promotion(tmp_path):
    g = make_gov(tmp_path, level_seed={"level": L3_NOTIFY, "streak": 0,
                                       "approved": 0, "rejected": 0, "incidents": 0})
    d = g.authorize("writer", "tool:write_file", "out/spec.md")
    assert d.allowed and d.needs_approval              # forced gate at any level

def test_rejection_resets_streak(tmp_path):
    g = make_gov(tmp_path)
    for _ in range(10):
        g.record_outcome("r", "approved", "writer")
    g.record_outcome("r", "rejected", "writer")
    assert g.tracker.state["writer"]["streak"] == 0

def test_incident_demotes_to_observe_and_blocks(tmp_path):
    g = make_gov(tmp_path, level_seed={"level": L3_NOTIFY, "streak": 50,
                                       "approved": 200, "rejected": 0, "incidents": 0})
    g.record_outcome("r", "incident", "writer", approver="risk-team")
    assert g.tracker.level("writer") == L1_OBSERVE
    d = g.authorize("writer", "model:complete")
    assert not d.allowed and d.reason == "observe_only"
    events = [json.loads(l)["event"] for l in
              (tmp_path / "receipts.jsonl").read_text().splitlines()]
    assert "autonomy_demoted" in events

def test_incidents_block_promotion_forever_until_reset(tmp_path):
    g = make_gov(tmp_path)
    g.record_outcome("r", "incident", "writer")
    for _ in range(200):
        g.record_outcome("r", "approved", "writer")
    assert g.tracker.level("writer") == L1_OBSERVE + 0 or True
    # after incident, level went to L1; approvals raise streak but promotion
    # requires incidents == 0, so agent stays put until ops resets the record
    assert g.tracker.state["writer"]["incidents"] == 1
    assert g.tracker.level("writer") == 1


# ── signed receipts ────────────────────────────────────────────────────
def test_receipts_verify_and_detect_tamper_and_forgery(tmp_path):
    led = SignedReceiptLedger(tmp_path / "r.jsonl")
    led.record("call_allowed", agent_id="writer", action="model:complete")
    led.record("outcome", outcome="approved", agent_id="writer")
    assert led.verify()[0]

    lines = (tmp_path / "r.jsonl").read_text().splitlines()
    rec = json.loads(lines[0]); rec["agent_id"] = "attacker"
    lines[0] = json.dumps(rec, sort_keys=True)
    (tmp_path / "r.jsonl").write_text("\n".join(lines) + "\n")
    ok, why = SignedReceiptLedger(tmp_path / "r.jsonl").verify()
    assert not ok and "line 1" in why

def test_forged_record_with_valid_hash_fails_signature(tmp_path):
    """An attacker can recompute hashes — but cannot sign without the key."""
    import hashlib as h, json as j
    led = SignedReceiptLedger(tmp_path / "r.jsonl")
    led.record("call_allowed", agent_id="writer", action="model:complete")
    rec = {"receipt_id": "x", "ts": "2026-01-01T00:00:00+00:00",
           "event": "call_allowed", "agent_id": "writer",
           "action": "tool:delete_everything",
           "prev_hash": j.loads((tmp_path / "r.jsonl").read_text())["record_hash"]}
    body = j.dumps(rec, sort_keys=True).encode()
    rec["record_hash"] = h.sha256(body).hexdigest()
    rec["signature"] = "0" * 64                       # no key → can't sign
    with (tmp_path / "r.jsonl").open("a") as f:
        f.write(j.dumps(rec, sort_keys=True) + "\n")
    ok, why = SignedReceiptLedger(tmp_path / "r.jsonl").verify()
    assert not ok and "signature invalid" in why

def test_missing_key_refuses_to_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PREFECTOS_SIGNING_KEY", raising=False)
    led = SignedReceiptLedger(tmp_path / "r.jsonl")
    with pytest.raises(RuntimeError):
        led.record("call_allowed", agent_id="w")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ── shadow mode, circuit breaker, replay ───────────────────────────────
def make_gov2(tmp_path, shadow=False):
    from agent_governance import CircuitBreaker
    eng = PolicyEngine({"writer": AgentPolicy("writer",
        allow=["model:complete"], max_calls_per_run=99)})
    return Governor(eng, AutonomyTracker(tmp_path/"a.json"),
                    SignedReceiptLedger(tmp_path/"r.jsonl"),
                    breaker=CircuitBreaker(tmp_path/"b.json"), shadow=shadow)

def test_shadow_mode_never_blocks_but_receipts(tmp_path):
    g = make_gov2(tmp_path, shadow=True)
    d = g.authorize("writer", "tool:delete_everything")   # not allowlisted
    assert d.allowed and d.reason == "shadow:not_in_allowlist"
    d2 = g.authorize("writer", "model:complete")
    assert d2.allowed and not d2.needs_approval           # no gating in shadow
    events = [json.loads(l)["event"] for l in
              (tmp_path/"r.jsonl").read_text().splitlines()]
    assert events == ["shadow_denied", "call_allowed"]

def test_circuit_breaker_freezes_and_is_receipted(tmp_path):
    g = make_gov2(tmp_path)
    assert g.authorize("writer", "model:complete").allowed
    g.freeze("writer", by="risk-team")
    d = g.authorize("writer", "model:complete")
    assert not d.allowed and d.reason == "circuit_breaker"
    g.unfreeze("writer", by="risk-team")
    assert g.authorize("writer", "model:complete").allowed
    events = [json.loads(l)["event"] for l in
              (tmp_path/"r.jsonl").read_text().splitlines()]
    assert "breaker_frozen" in events and "breaker_released" in events

def test_breaker_outranks_shadow(tmp_path):
    g = make_gov2(tmp_path, shadow=True)
    g.freeze(None, by="board")                            # freeze ALL
    d = g.authorize("writer", "model:complete")
    assert not d.allowed and d.reason == "circuit_breaker"

def test_replay_reports_would_block(tmp_path):
    from agent_governance import replay_policy
    g = make_gov2(tmp_path)
    g.authorize("writer", "model:complete")
    g.authorize("writer", "model:complete")
    stricter = tmp_path/"p2.json"
    stricter.write_text(json.dumps({"agents":[
        {"agent_id":"writer","allow":["tool:read_file"]}]}))
    rep = replay_policy(stricter, tmp_path/"r.jsonl")
    assert rep["calls_replayed"] == 2 and rep["would_block"] == 2
    assert rep["blocked_calls"][0]["reason"] == "not_in_allowlist"

def test_shadow_report_census(tmp_path):
    from agent_governance import shadow_report
    g = make_gov2(tmp_path, shadow=True)
    g.authorize("writer", "model:complete")
    g.authorize("writer", "tool:hack_the_planet")
    rep = shadow_report(tmp_path/"r.jsonl")
    assert rep["agents_observed"] == 1
    assert rep["would_be_denied_total"] == 1
    assert rep["census"]["writer"]["calls"] == 2
