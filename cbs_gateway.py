# CBS Governance Gateway — the PrefectOS sidecar in front of the core.
"""Agents never call the core; they call THIS. Every request is mapped to
(agent, action, resource), authorized by the deny-by-default Governor,
receipted, and only then forwarded to the core.

Identity: X-Agent-Id header IN THIS MOCK ONLY — production binds identity
via mTLS client certs or service-account tokens (see integration guide);
a self-declared header is exactly what real deployments must NOT trust.

Human gate in this mock: a gated action forwards only when X-Approver is
present (simulating the approval UI); the approver is sealed into the
outcome receipt. Absent → 412 with the receipt id, nothing forwarded.

Run:  CBS_URL=http://127.0.0.1:9000 uvicorn cbs_gateway:app --port 9100
"""
from __future__ import annotations
import json
import os
import urllib.request
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from agent_governance import Governor

CBS_URL = os.getenv("CBS_URL", "http://127.0.0.1:9000")
app = FastAPI(title="PrefectOS CBS Gateway")

# (method, path-prefix) → action; resource = remainder of the path
ROUTES = [
    ("GET",  "/cbs/accounts",       "cbs:read"),
    ("GET",  "/cbs/customers",      "cbs:read"),
    ("GET",  "/cbs/beneficiaries",  "cbs:read"),
    ("POST", "/cbs/customers",      "cbs:master_write"),   # CIF creation
    ("POST", "/cbs/accounts",       "cbs:master_write"),   # account opening
    ("POST", "/cbs/tx/cash",        "cbs:payment"),        # cash dep/wdl
    ("POST", "/cbs/payments",       "cbs:payment"),
    ("PUT",  "/cbs/customers",      "cbs:master_write"),
    ("PUT",  "/cbs/beneficiaries",  "cbs:master_write"),
    ("POST", "/cbs/eod",            "cbs:batch"),
]


def classify(method: str, path: str) -> tuple[str, str]:
    for m, prefix, action in ROUTES:
        if method == m and path.startswith(prefix):
            return action, path[len("/cbs/"):]
    return "cbs:unknown", path


def forward(method: str, path: str, body: bytes, ctype: str) -> tuple[int, bytes]:
    req = urllib.request.Request(CBS_URL + path, data=body or None, method=method,
                                 headers={"Content-Type": ctype or "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# ── demo console + receipt taps (mock only; prod uses governance_api) ──
@app.get("/meta/receipts")
def meta_receipts(n: int = 12):
    import json as _j
    from agent_governance import STATE_DIR
    f = STATE_DIR / "receipts.jsonl"
    if not f.exists():
        return {"receipts": []}
    lines = [l for l in f.read_text().splitlines() if l.strip()]
    return {"receipts": [_j.loads(l) for l in lines[-n:]][::-1]}


@app.get("/meta/verify")
def meta_verify():
    from agent_governance import STATE_DIR, SignedReceiptLedger
    f = STATE_DIR / "receipts.jsonl"
    if not f.exists():
        return {"valid": True, "detail": "no receipts"}
    ok, detail = SignedReceiptLedger(f).verify()
    return {"valid": ok, "detail": detail}


@app.get("/", response_class=HTMLResponse)
def console():
    portal = Path(__file__).parent / "cbs_portal.html"
    if portal.exists():
        return portal.read_text()
    return CONSOLE_HTML


# pluggable for tests
app.state.forward = forward


@app.api_route("/cbs/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def gateway(rest: str, request: Request):
    path = "/cbs/" + rest
    agent = request.headers.get("X-Agent-Id", "")
    approver = request.headers.get("X-Approver", "")
    action, resource = classify(request.method, path)

    gov = Governor.load()
    d = gov.authorize(agent or "UNIDENTIFIED", action, resource)
    if not d.allowed:
        return Response(json.dumps({"error": "governance_denied",
                                    "reason": d.reason,
                                    "receipt": d.receipt_id}),
                        status_code=403, media_type="application/json")
    if d.needs_approval:
        if not approver:
            return Response(json.dumps({"error": "approval_required",
                                        "action": action, "resource": resource,
                                        "receipt": d.receipt_id}),
                            status_code=412, media_type="application/json")
        gov.record_outcome(d.receipt_id, "approved", agent, approver=approver)

    body = await request.body()
    status, payload = app.state.forward(request.method, path, body,
                                        request.headers.get("Content-Type", ""))
    if not d.needs_approval:
        gov.record_outcome(d.receipt_id, "executed", agent)
    return Response(payload, status_code=status, media_type="application/json")


CONSOLE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>PrefectOS · CBS Gateway Tester</title>
<style>
 body{font-family:'Segoe UI',system-ui,sans-serif;background:#f7f8fd;color:#0f172a;margin:0;padding:24px;}
 h1{font-size:18px;margin:0 0 4px;} .sub{font-size:13px;color:#64748b;margin-bottom:16px;}
 .row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;align-items:center;}
 select,input{font-size:13px;padding:8px 10px;border:1px solid #e2e8f0;border-radius:8px;}
 button{font-size:13px;padding:9px 14px;border:1px solid #e2e8f0;border-radius:9px;background:#fff;cursor:pointer;}
 button.op{border-color:#c7d2fe;color:#4f46e5;font-weight:600;}
 #vfy{background:#4f46e5;color:#fff;border:none;}
 .log{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:4px 0;min-height:120px;}
 .ln{padding:8px 14px;border-bottom:1px solid #eef2f7;font:12px Consolas,monospace;}
 .ln:last-child{border:none}
 .ok{color:#15803d}.deny{color:#b91c1c;font-weight:600}.hold{color:#b45309;font-weight:600}
 .sub2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#64748b;font-weight:600;margin:16px 0 6px;}
 .recs{background:#fff;border:1px solid #e2e8f0;border-radius:12px;}
 .rec{display:flex;gap:8px;padding:6px 12px;border-bottom:1px solid #eef2f7;font:11px Consolas,monospace;}
 .rec:last-child{border:none}
 .ev-ok{color:#15803d}.ev-gate{color:#b45309}.ev-deny{color:#b91c1c}
 .sig{color:#4f46e5;margin-left:auto}
 #vres{font-size:13px;font-weight:600;margin-left:8px;}
 #vres.good{color:#15803d}#vres.bad{color:#b91c1c}
</style></head><body>
<h1>⬡ PrefectOS — CBS Gateway Tester</h1>
<div class="sub">Every button calls the mock Finacle core THROUGH the governance gateway. Watch what the guard does.</div>
<div class="row">
 <label>Agent <select id="agent">
   <option value="">(unidentified)</option>
   <option>cbs.teller_agent</option><option>cbs.payments_agent</option><option>cbs.recon_agent</option>
 </select></label>
 <label>Approver <input id="approver" placeholder="none" size="12"></label>
</div>
<div class="row">
 <button class="op" data-op="balance">Read balance SB1001</button>
 <button class="op" data-op="transfer">Transfer ₹50,000 →</button>
 <button class="op" data-op="benef">Change beneficiary bank a/c</button>
 <button class="op" data-op="eod">Run EOD batch</button>
 <button id="vfy">Verify receipt chain</button><span id="vres"></span>
</div>
<div class="log" id="log"><div class="ln" style="color:#94a3b8">Responses appear here…</div></div>
<div class="sub2">Signed receipts (live)</div>
<div class="recs" id="recs"></div>
<script>
const $=id=>document.getElementById(id);
function line(cls, txt){const d=document.createElement('div');d.className='ln '+cls;d.textContent=txt;
 const log=$('log'); if(log.firstChild&&log.firstChild.textContent.includes('appear here'))log.innerHTML='';
 log.prepend(d); while(log.children.length>6)log.removeChild(log.lastChild); refreshRecs();}
async function call(method,path,body){
 const h={'Content-Type':'application/json'};
 const a=$('agent').value, ap=$('approver').value.trim();
 if(a)h['X-Agent-Id']=a; if(ap)h['X-Approver']=ap;
 const r=await fetch(path,{method,headers:h,body:body?JSON.stringify(body):undefined});
 const j=await r.json().catch(()=>({}));
 const who=(a||'unidentified')+(ap?(' + '+ap):'');
 if(r.status===403)line('deny',`DENIED 403 · ${who} · ${j.reason||''} · receipt ${j.receipt||''}`);
 else if(r.status===412)line('hold',`HELD 412 · ${who} · approval required · receipt ${j.receipt||''}`);
 else line('ok',`OK ${r.status} · ${who} · ${JSON.stringify(j).slice(0,90)}`);
}
document.querySelectorAll('.op').forEach(b=>b.onclick=()=>{
 const op=b.dataset.op;
 if(op==='balance')call('GET','/cbs/accounts/SB1001/balance');
 if(op==='transfer')call('POST','/cbs/payments/transfer',{from:'CA2001',to:'SB1001',amount:50000});
 if(op==='benef')call('PUT','/cbs/beneficiaries/B901/bank-account',{bank_account:'EVIL000999999'});
 if(op==='eod')call('POST','/cbs/eod/run');
});
$('vfy').onclick=async()=>{const j=await(await fetch('/meta/verify')).json();
 const v=$('vres'); v.textContent=j.valid?'⛓ VALID':'⛓ BROKEN: '+j.detail;
 v.className=j.valid?'good':'bad';};
async function refreshRecs(){const j=await(await fetch('/meta/receipts?n=8')).json();
 $('recs').innerHTML=(j.receipts||[]).map(r=>{
  const cls=r.event.includes('denied')?'ev-deny':r.event.includes('gated')?'ev-gate':'ev-ok';
  return `<div class=rec><span class=${cls}>${r.event}</span><span>${r.agent_id||''} ${r.action||''} ${r.resource||r.reason||r.outcome||''} ${r.approver?('· by '+r.approver):''}</span><span class=sig>sig ${String(r.signature||'').slice(0,6)}✓</span></div>`;
 }).join('');}
refreshRecs();
</script></body></html>"""
