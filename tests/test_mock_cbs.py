"""Governed mock-CBS tests: the gateway enforces policy in front of a
Finacle-like core. Offline — the gateway's forward() is pointed at the
mock core's TestClient."""
import json, os, sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("PREFECTOS_SIGNING_KEY", "test-key-not-for-production")

import agent_governance
import cbs_gateway
import mock_cbs


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # isolate governance state; activate the banking pack.
    # Governor.load's default state_dir binds at def-time, so patch the
    # gateway's Governor handle with a loader pinned to tmp_path.
    from types import SimpleNamespace
    from agent_governance import Governor, PackRegistry
    reg = PackRegistry(state_dir=tmp_path); reg.set_active("banking", True)
    monkeypatch.setattr(cbs_gateway, "Governor",
        SimpleNamespace(load=lambda: Governor.load(state_dir=tmp_path)))
    core = TestClient(mock_cbs.app)
    def fake_forward(method, path, body, ctype):
        r = core.request(method, path, content=body or None,
                         headers={"Content-Type": ctype or "application/json"})
        return r.status_code, r.content
    cbs_gateway.app.state.forward = fake_forward
    gw = TestClient(cbs_gateway.app)
    # reset core balances between tests
    mock_cbs.ACCOUNTS["SB1001"]["balance"] = 245000.00
    mock_cbs.ACCOUNTS["CA2001"]["balance"] = 1830000.00
    mock_cbs.BENEFICIARIES["B901"]["bank_account"] = "UTIB000123456"
    return gw, tmp_path


def receipts(tmp_path):
    f = tmp_path / "receipts.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.exists() else []


def test_unidentified_caller_denied(env):
    gw, tp = env
    r = gw.get("/cbs/accounts/SB1001/balance")
    assert r.status_code == 403
    assert r.json()["reason"] == "unknown_agent"


def test_teller_balance_read_gated_then_flows(env):
    gw, tp = env
    h = {"X-Agent-Id": "cbs.teller_agent"}
    r = gw.get("/cbs/accounts/SB1001/balance", headers=h)
    assert r.status_code == 412                      # L2: approval required
    r = gw.get("/cbs/accounts/SB1001/balance",
               headers=h | {"X-Approver": "sarah.jenkins"})
    assert r.status_code == 200 and r.json()["balance"] == 245000.00


def test_payment_always_gated_and_posts_with_approver(env):
    gw, tp = env
    h = {"X-Agent-Id": "cbs.payments_agent"}
    body = {"from": "CA2001", "to": "SB1001", "amount": 50000}
    r = gw.post("/cbs/payments/transfer", json=body, headers=h)
    assert r.status_code == 412                      # money never moves ungated
    r = gw.post("/cbs/payments/transfer", json=body,
                headers=h | {"X-Approver": "r.mehta"})
    assert r.status_code == 200 and r.json()["status"] == "POSTED"
    assert mock_cbs.ACCOUNTS["SB1001"]["balance"] == 295000.00
    ev = [x["event"] for x in receipts(tp)]
    assert "call_gated" in ev
    outs = [x for x in receipts(tp) if x["event"] == "outcome"]
    assert outs[-1]["approver"] == "r.mehta"


def test_beneficiary_bank_change_denied_for_everyone(env):
    gw, tp = env
    for agent in ("cbs.teller_agent", "cbs.payments_agent", "cbs.recon_agent"):
        r = gw.put("/cbs/beneficiaries/B901/bank-account",
                   json={"bank_account": "EVIL000999999", "ifsc": "EVIL0000001"},
                   headers={"X-Agent-Id": agent, "X-Approver": "anyone"})
        assert r.status_code == 403, agent           # approver can't unlock policy
        assert r.json()["reason"] == "not_in_allowlist"
    assert mock_cbs.BENEFICIARIES["B901"]["bank_account"] == "UTIB000123456"


def test_payments_agent_cannot_touch_customer_master(env):
    gw, tp = env
    r = gw.put("/cbs/customers/C001", json={"name": "Hacked"},
               headers={"X-Agent-Id": "cbs.payments_agent", "X-Approver": "x"})
    assert r.status_code == 403
    assert mock_cbs.CUSTOMERS["C001"]["name"] == "R. Sharma"


def test_eod_gated_to_recon_agent_only(env):
    gw, tp = env
    r = gw.post("/cbs/eod/run", headers={"X-Agent-Id": "cbs.payments_agent",
                                          "X-Approver": "ops"})
    assert r.status_code == 403
    r = gw.post("/cbs/eod/run", headers={"X-Agent-Id": "cbs.recon_agent",
                                          "X-Approver": "ops.night"})
    assert r.status_code == 200 and r.json()["status"] == "EOD_COMPLETE"


def test_every_touch_is_receipted_and_chain_valid(env):
    gw, tp = env
    gw.get("/cbs/accounts/SB1001/balance",
           headers={"X-Agent-Id": "cbs.teller_agent", "X-Approver": "s"})
    gw.put("/cbs/beneficiaries/B901/bank-account", json={"bank_account": "X"},
           headers={"X-Agent-Id": "cbs.teller_agent"})
    from agent_governance import SignedReceiptLedger
    ok, detail = SignedReceiptLedger(tp / "receipts.jsonl").verify()
    assert ok, detail
    ev = [x["event"] for x in receipts(tp)]
    assert "call_gated" in ev and "call_denied" in ev
