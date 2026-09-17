"""Recorded E2E: the Agent OS console — one governance spine, any industry.
Pack catalog with live install (Insurance activated on camera, receipted),
cross-domain agent roster with domain filters, SAP fraud denial in the OS
event log, chain verification. Video + shots → e2e_artifacts_aos/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
ART = Path("e2e_artifacts_aos"); ART.mkdir(exist_ok=True)
results = []

def step(name, fn):
    t0=time.time()
    try: fn(); results.append((name,"PASS",round(time.time()-t0,2))); print(f"  PASS  {name}")
    except Exception as e:
        results.append((name,f"FAIL: {str(e)[:110]}",round(time.time()-t0,2)))
        print(f"  FAIL  {name}: {e}"); raise

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width":1280,"height":800},
        record_video_dir=str(ART/"video"), record_video_size={"width":1280,"height":800})
    ctx.add_init_script("""
        localStorage.setItem('prefectos_user_id','e2e-sarah');
        localStorage.setItem('prefectos_user_name','Sarah Jenkins');
        localStorage.setItem('prefectos_user_role','approver');""")
    page = ctx.new_page()
    shot = lambda n: page.screenshot(path=str(ART/f"{n}.png"), full_page=True)

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        page.get_by_text("Launch Workspace Demo").click()
        expect(page.locator(".ln-item", has_text="Agent OS")).to_be_visible(timeout=10000)
        shot("01_rail_agentos")
    step("T1 'Agent OS' suite appears in the rail (badge: OS)", t1)

    def t2():
        page.locator(".ln-item", has_text="Agent OS").click()
        expect(page.locator(".aos-title")).to_have_text("Agent OS")
        expect(page.locator(".gv-pill.ok", has_text="chain valid")).to_be_visible()
        expect(page.locator(".aos-pack")).to_have_count(5)
        expect(page.locator(".aos-pack.active")).to_have_count(3)
        shot("02_agentos_console")
    step("T2 console: 5 industry packs, 3 installed, chain valid", t2)

    def t3():
        ins = page.locator(".aos-pack", has_text="Insurance")
        expect(ins).to_contain_text("not installed")
        ins.locator(".aos-switch").click()
        expect(ins.locator(".aos-switch")).to_have_class(lambda c: "on" in c) \
            if False else expect(ins).to_contain_text("governed & running", timeout=8000)
        expect(page.locator(".gv-rec", has_text="pack_activated").first).to_be_visible(timeout=8000)
        shot("03_insurance_installed_live")
    step("T3 Insurance pack installed live · pack_activated receipt appears", t3)

    def t4():
        d = ctx.request.get(BASE+"/governance/agents").json()
        doms = {a["domain"] for a in d["agents"]}
        assert {"banking","sap","salesforce","insurance"} <= doms, doms
        ins_agents = [a for a in d["agents"] if a["domain"]=="insurance"]
        assert len(ins_agents) == 3, ins_agents
    step("T4 backend: insurance agents governed the moment the pack installed", t4)

    def t5():
        page.locator(".aos-dom", has_text="sap").click()
        expect(page.locator(".gv-card")).to_have_count(2)
        expect(page.locator(".gv-card", has_text="sap.ap_invoice_agent")).to_be_visible()
        shot("04_sap_domain_filter")
        page.locator(".aos-dom", has_text="all").click()
    step("T5 domain filter: SAP shows exactly its 2 agents", t5)

    def t6():
        deny = page.locator(".gv-rec", has_text="LFA1.bank_account").first
        expect(deny).to_be_visible()
        expect(deny).to_contain_text("call_denied")
        shot("05_sap_fraud_denial_in_log")
    step("T6 OS event log shows the SAP vendor-bank fraud denial", t6)

    def t7():
        v = ctx.request.get(BASE+"/governance/verify").json()
        assert v["valid"], v
        recs = ctx.request.get(BASE+"/governance/receipts?n=100").json()["receipts"]
        events = {r["event"] for r in recs}
        assert "pack_activated" in events and "call_denied" in events, events
    step("T7 chain VALID · pack installs + denials all signed in one ledger", t7)

    page.wait_for_timeout(1200)
    vp = page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"agentos_e2e.webm")
    print(f"\nvideo: {ART/'agentos_e2e.webm'}")

report = {"suite":"Agent OS console — recorded E2E",
          "passed":sum(1 for _,s,_ in results if s=="PASS"),
          "failed":sum(1 for _,s,_ in results if s!="PASS"),
          "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
