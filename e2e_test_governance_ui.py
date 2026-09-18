"""Recorded E2E: the NEW Governance suite UI.
Roster with earned levels + streaks, signed receipts feed, chain-valid
pill, per-agent circuit breaker (freeze → FROZEN tag + receipt → release),
and freeze-all. Video + screenshots to e2e_artifacts3/."""
import json, re, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
ART = Path("e2e_artifacts3"); ART.mkdir(exist_ok=True)
results = []

def step(name, fn):
    t0 = time.time()
    try:
        fn(); results.append((name,"PASS",round(time.time()-t0,2))); print(f"  PASS  {name}")
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
        expect(page.get_by_text("Loan Processing Suite")).to_be_visible(timeout=10000)
        expect(page.locator(".ln-item", has_text="Governance")).to_be_visible()
        shot("01_rail_with_governance")
    step("T1 Governance appears in the suites rail", t1)

    def t2():
        page.locator(".ln-item", has_text="Governance").click()
        expect(page.locator(".gv-title")).to_have_text("Agent governance")
        expect(page.locator(".gv-pill.ok").first).to_contain_text("policy enforced")
        expect(page.locator(".gv-pill").nth(1)).to_contain_text("chain valid")
        shot("02_governance_panel")
    step("T2 panel opens: enforce mode + chain-valid pills", t2)

    def t3():
        expect(page.locator(".gv-card")).to_have_count(6)
        clf = page.locator(".gv-card", has_text="email_classifier")
        expect(clf.locator(".gv-lvl")).to_contain_text("L2 approve")
        expect(clf).to_contain_text("18 approved")
        expect(clf.locator(".gv-next")).to_contain_text("18/25")
        shot("03_agent_cards_streaks")
    step("T3 six agent cards · classifier shows 18/25 streak to L3", t3)

    def t4():
        recs = page.locator(".gv-rec")
        expect(recs.first).to_be_visible()
        expect(page.locator(".gv-ev.deny", has_text="call_denied").first).to_be_visible()
        expect(page.locator(".gv-sig").first).to_contain_text("✓")
        shot("04_signed_receipts_feed")
    step("T4 receipts feed shows the executor denial + signatures", t4)

    def t5():
        card = page.locator(".gv-card", has_text="executor")
        card.locator(".gv-brake").click()
        expect(card.locator(".gv-frozen-tag")).to_be_visible(timeout=8000)
        expect(page.locator(".gv-rec", has_text="breaker_frozen").first).to_be_visible(timeout=8000)
        shot("05_executor_FROZEN")
    step("T5 Freeze executor → FROZEN tag + breaker_frozen receipt", t5)

    def t6():
        d = ctx.request.get(BASE+"/governance/agents").json()
        ex = [a for a in d["agents"] if a["agent_id"]=="executor"][0]
        assert ex["frozen"] is True, ex
        card = page.locator(".gv-card", has_text="executor")
        card.locator(".gv-brake").click()
        expect(card.locator(".gv-frozen-tag")).to_have_count(0, timeout=8000)
        shot("06_executor_released")
    step("T6 backend confirms frozen · Release restores the agent", t6)

    def t7():
        v = ctx.request.get(BASE+"/governance/verify").json()
        assert v["valid"], v
    step("T7 receipts chain verifies VALID after breaker activity", t7)

    page.wait_for_timeout(1200)
    vp = page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"governance_ui_e2e.webm")
    print(f"\nvideo: {ART/'governance_ui_e2e.webm'}")

report = {"suite":"Governance UI — recorded E2E",
          "passed":sum(1 for _,s,_ in results if s=="PASS"),
          "failed":sum(1 for _,s,_ in results if s!="PASS"),
          "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
