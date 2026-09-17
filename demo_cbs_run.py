"""End-to-end demo against the mock Finacle-like core, governed live.
Start (3 terminals or background):
  export PREFECTOS_SIGNING_KEY=demo-key
  uvicorn mock_cbs:app --port 9000
  CBS_URL=http://127.0.0.1:9000 uvicorn cbs_gateway:app --port 9100
  python3 demo_cbs_run.py
"""
import json, os, urllib.request, urllib.error

GW = os.getenv("GW_URL", "http://127.0.0.1:9100")

def call(method, path, agent=None, approver=None, body=None):
    h = {"Content-Type": "application/json"}
    if agent: h["X-Agent-Id"] = agent
    if approver: h["X-Approver"] = approver
    req = urllib.request.Request(GW + path, method=method, headers=h,
        data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def show(title, res):
    code, body = res
    print(f"\n── {title}\n   HTTP {code} · {json.dumps(body)[:140]}")

from agent_governance import PackRegistry
PackRegistry().set_active("banking", True)
print("banking pack: ACTIVE")

show("1. Unidentified script reads a balance → DENIED (unknown agent)",
     call("GET", "/cbs/accounts/SB1001/balance"))
show("2. Teller agent reads balance, no approver → HELD 412 (L2 gate)",
     call("GET", "/cbs/accounts/SB1001/balance", agent="cbs.teller_agent"))
show("3. Same call, Sarah approves → 200, balance served",
     call("GET", "/cbs/accounts/SB1001/balance", agent="cbs.teller_agent",
          approver="sarah.jenkins"))
show("4. Payments agent moves ₹50,000 with controller approval → POSTED",
     call("POST", "/cbs/payments/transfer", agent="cbs.payments_agent",
          approver="r.mehta", body={"from":"CA2001","to":"SB1001","amount":50000}))
show("5. Payments agent tries beneficiary bank-account change → DENIED (fraud path, in nobody's book — approver cannot unlock policy)",
     call("PUT", "/cbs/beneficiaries/B901/bank-account", agent="cbs.payments_agent",
          approver="r.mehta", body={"bank_account":"EVIL000999999"}))
show("6. Recon agent runs EOD with night-ops approval → EOD_COMPLETE",
     call("POST", "/cbs/eod/run", agent="cbs.recon_agent", approver="ops.night"))

import subprocess
out = subprocess.run(["python3","agent_governance.py","--verify"],
                     capture_output=True, text=True, env=os.environ)
print("\n──", out.stdout.strip())
print("\nEvery touch of the core — served, held, or refused — is on the signed chain.")
