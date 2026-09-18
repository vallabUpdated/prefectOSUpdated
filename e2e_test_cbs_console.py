"""Recorded E2E: mock Finacle core behind the PrefectOS governance gateway,
driven through the CBS Gateway Tester console. Six scenarios on camera:
unknown caller, held-then-approved read, approved payment, fraud denial
(approver can't unlock policy), EOD segregation, chain verify.
Video + shots → e2e_artifacts_cbs/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:9100"; ART=Path("e2e_artifacts_cbs"); ART.mkdir(exist_ok=True)
results=[]
def step(name,fn):
    t0=time.time()
    try: fn(); results.append((name,"PASS",round(time.time()-t0,2))); print(f"  PASS  {name}")
    except Exception as e:
        results.append((name,f"FAIL: {str(e)[:110]}",round(time.time()-t0,2)))
        print(f"  FAIL  {name}: {e}"); raise

with sync_playwright() as p:
    browser=p.chromium.launch()
    ctx=browser.new_context(viewport={"width":1280,"height":800},
        record_video_dir=str(ART/"video"), record_video_size={"width":1280,"height":800})
    page=ctx.new_page()
    shot=lambda n: page.screenshot(path=str(ART/f"{n}.png"), full_page=True)
    log0=lambda: page.locator("#log .ln").first

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        expect(page.locator("h1")).to_contain_text("CBS Gateway Tester")
        shot("01_console")
    step("T1 gateway console loads (mock Finacle behind it)", t1)

    def t2():
        page.get_by_role("button", name="Read balance SB1001").click()
        expect(log0()).to_contain_text("DENIED 403", timeout=8000)
        expect(log0()).to_contain_text("unknown_agent")
        shot("02_unknown_denied")
    step("T2 unidentified caller → DENIED (deny-by-default)", t2)

    def t3():
        page.locator("#agent").select_option("cbs.teller_agent")
        page.get_by_role("button", name="Read balance SB1001").click()
        expect(log0()).to_contain_text("HELD 412", timeout=8000)
        page.locator("#approver").fill("sarah.jenkins")
        page.get_by_role("button", name="Read balance SB1001").click()
        expect(log0()).to_contain_text("OK 200", timeout=8000)
        expect(log0()).to_contain_text("245000")
        shot("03_read_held_then_approved")
    step("T3 teller read: HELD without approver → served with Sarah's approval", t3)

    def t4():
        page.locator("#agent").select_option("cbs.payments_agent")
        page.locator("#approver").fill("r.mehta")
        page.get_by_role("button", name="Transfer ₹50,000 →").click()
        expect(log0()).to_contain_text("POSTED", timeout=8000)
        expect(page.locator("#recs .rec").first).to_contain_text("by r.mehta")
        shot("04_payment_posted_with_approver")
    step("T4 ₹50,000 transfer POSTED · approver sealed in the receipt", t4)

    def t5():
        page.get_by_role("button", name="Change beneficiary bank a/c").click()
        expect(log0()).to_contain_text("DENIED 403", timeout=8000)
        expect(log0()).to_contain_text("not_in_allowlist")
        shot("05_fraud_denied_despite_approver")
    step("T5 beneficiary bank change DENIED even with approver — policy outranks approval", t5)

    def t6():
        page.get_by_role("button", name="Run EOD batch").click()
        expect(log0()).to_contain_text("DENIED 403", timeout=8000)   # payments agent
        page.locator("#agent").select_option("cbs.recon_agent")
        page.locator("#approver").fill("ops.night")
        page.get_by_role("button", name="Run EOD batch").click()
        expect(log0()).to_contain_text("EOD_COMPLETE", timeout=8000)
        shot("06_eod_segregated")
    step("T6 EOD: payments agent refused, recon agent runs it — duty segregation", t6)

    def t7():
        page.get_by_role("button", name="Verify receipt chain").click()
        expect(page.locator("#vres")).to_contain_text("VALID", timeout=8000)
        recs = page.locator("#recs .rec")
        expect(recs.first).to_be_visible()
        shot("07_chain_valid")
    step("T7 chain verifies VALID on screen · receipts feed live", t7)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"cbs_gateway_e2e.webm")
    print(f"\nvideo: {ART/'cbs_gateway_e2e.webm'}")

report={"suite":"Mock CBS behind PrefectOS gateway — recorded E2E",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
