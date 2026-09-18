# Mock Core Banking System — a Finacle-like core for testing PrefectOS
# governance. In-memory, deliberately simple, API shapes modeled on
# CBS conventions (scheme codes, SOL ids, maker-checker semantics).
"""Run:  uvicorn mock_cbs:app --port 9000
NEVER exposed directly in a governed deployment — agents reach it only
through cbs_gateway (the governance sidecar). The egress rule that makes
this core unreachable except via the gateway is what turns policy from
suggestion into control.
"""
from __future__ import annotations
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Body
import uuid

app = FastAPI(title="MockCBS (Finacle-like core)")

CUSTOMERS = {
    "C001": {"cust_id": "C001", "name": "R. Sharma", "kyc_status": "VERIFIED",
             "segment": "RETAIL", "sol_id": "1001"},
    "C002": {"cust_id": "C002", "name": "Acme Traders", "kyc_status": "VERIFIED",
             "segment": "MSME", "sol_id": "1002"},
}
ACCOUNTS = {
    "SB1001": {"acct": "SB1001", "cust_id": "C001", "scheme": "SBGEN",
               "balance": 245000.00, "status": "ACTIVE"},
    "CA2001": {"acct": "CA2001", "cust_id": "C002", "scheme": "CAGEN",
               "balance": 1830000.00, "status": "ACTIVE"},
}
BENEFICIARIES = {
    "B901": {"ben_id": "B901", "name": "Sunrise Suppliers",
             "bank_account": "UTIB000123456", "ifsc": "UTIB0000012"},
}
TXNS: list[dict] = []
EOD = {"running": False, "last_run": None}


def _now(): return datetime.now(timezone.utc).isoformat()


@app.get("/cbs/accounts/{acct}/balance")
def balance(acct: str):
    a = ACCOUNTS.get(acct)
    if not a: raise HTTPException(404, "E-ACCT-404: account not found")
    return {"acct": acct, "balance": a["balance"], "currency": "INR",
            "status": a["status"], "as_of": _now()}


@app.get("/cbs/accounts/{acct}/transactions")
def txns(acct: str, n: int = 20):
    return {"acct": acct,
            "transactions": [t for t in TXNS if acct in (t["from"], t["to"])][-n:]}


@app.post("/cbs/payments/transfer")
def transfer(body: dict = Body(...)):
    src, dst, amt = body.get("from"), body.get("to"), float(body.get("amount", 0))
    if EOD["running"]:
        raise HTTPException(423, "E-EOD-423: core locked, EOD batch in progress")
    a, b = ACCOUNTS.get(src), ACCOUNTS.get(dst)
    if not a or not b: raise HTTPException(404, "E-ACCT-404")
    if amt <= 0 or a["balance"] < amt:
        raise HTTPException(422, "E-FUNDS-422: insufficient funds")
    a["balance"] -= amt; b["balance"] += amt
    txn = {"txn_id": "T" + uuid.uuid4().hex[:10].upper(), "from": src, "to": dst,
           "amount": amt, "ts": _now(), "channel": "AGENT"}
    TXNS.append(txn)
    return {"status": "POSTED", **txn}


@app.get("/cbs/customers/{cust_id}")
def customer(cust_id: str):
    c = CUSTOMERS.get(cust_id)
    if not c: raise HTTPException(404, "E-CUST-404")
    return c


@app.put("/cbs/customers/{cust_id}")
def update_customer(cust_id: str, body: dict = Body(...)):
    c = CUSTOMERS.get(cust_id)
    if not c: raise HTTPException(404, "E-CUST-404")
    c.update({k: v for k, v in body.items() if k in ("name", "segment")})
    return {"status": "UPDATED", "customer": c}


@app.put("/cbs/beneficiaries/{ben_id}/bank-account")
def change_beneficiary_account(ben_id: str, body: dict = Body(...)):
    """THE fraud target: redirect a beneficiary's payouts."""
    b = BENEFICIARIES.get(ben_id)
    if not b: raise HTTPException(404, "E-BEN-404")
    b["bank_account"] = body.get("bank_account", b["bank_account"])
    b["ifsc"] = body.get("ifsc", b["ifsc"])
    return {"status": "UPDATED", "beneficiary": b}


@app.post("/cbs/eod/run")
def run_eod():
    EOD["running"] = True
    for t in TXNS: t["posted_eod"] = True
    EOD.update(running=False, last_run=_now())
    return {"status": "EOD_COMPLETE", "posted": len(TXNS), "at": EOD["last_run"]}
