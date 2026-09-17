"""Recorded E2E: the interactive MockBank Teller Portal (governed CBS UI).
Approval modal on gated payments, policy toast on the fraud path, duty
segregation on EOD, live balances and receipts, chain verify — on camera.
Video + shots → e2e_artifacts_portal/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:9100"; ART=Path("e2e_artifacts_portal"); ART.mkdir(exist_ok=True)
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

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        expect(page.locator(".brand")).to_contain_text("MockBank")
        expect(page.locator(".acct")).to_have_count(2, timeout=10000)
        expect(page.locator(".acct").first).to_contain_text("₹")
        shot("01_dashboard_live_balances")
    step("T1 teller portal loads · live ₹ balances from the governed core", t1)

    def t2():
        page.locator(".nav-btn", has_text="Payments").click()
        # teller identity cannot even initiate a payment — proof first:
        page.locator("#paygo").click()
        expect(page.locator(".toast.deny").last).to_contain_text("Blocked by policy", timeout=8000)
        shot("02a_teller_cannot_pay")
        # switch bot identity to the payments agent → now it gates
        page.locator("#agent").select_option("cbs.payments_agent")
        page.locator("#paygo").click()
        expect(page.locator("#gate")).to_have_class("on", timeout=8000) \
            if False else expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        expect(page.locator("#gatedesc")).to_contain_text("TRANSFER")
        expect(page.locator("#gatedesc")).to_contain_text("CA2001")
        shot("02_human_gate_modal")
    step("T2 teller denied payment · payments agent → human-gate modal", t2)

    def t3():
        page.locator("#gateno").click()
        expect(page.locator(".toast.hold").last).to_contain_text("rejected at the human gate", timeout=8000)
        shot("03_rejected_at_gate")
    step("T3 Reject → held toast, nothing executed", t3)

    def t4():
        page.locator("#paygo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        page.locator("#gatewho").fill("r.mehta")
        page.locator("#gateok").click()
        expect(page.locator(".toast.ok").last).to_contain_text("POSTED", timeout=8000)
        expect(page.locator(".toast.ok").last).to_contain_text("approved by r.mehta")
        shot("04_posted_with_approver")
    step("T4 approve as r.mehta → ₹50,000 POSTED · approver named in toast", t4)

    def t5():
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct", has_text="SB1001")).to_contain_text("2,95,000", timeout=10000)
        expect(page.locator(".rec", has_text="by r.mehta").first).to_be_visible()
        shot("05_balance_updated_receipt_feed")
    step("T5 dashboard: SB1001 now ₹2,95,000 · receipt shows r.mehta", t5)

    def t6():
        page.locator(".nav-btn", has_text="Beneficiaries").click()
        page.locator("#benedit").click()
        expect(page.locator(".toast.deny").last).to_contain_text("Blocked by policy", timeout=8000)
        expect(page.locator("#benac")).to_have_text("UTIB000123456")
        shot("06_fraud_blocked_toast")
    step("T6 beneficiary bank change → policy toast · account number untouched", t6)

    def t7():
        page.locator(".nav-btn", has_text="EOD Batch").click()
        page.locator("#eodgo").click()
        expect(page.locator(".toast.deny").last).to_contain_text("Blocked by policy", timeout=8000)  # teller can't
        page.locator("#agent").select_option("cbs.recon_agent")
        page.locator("#eodgo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        page.locator("#gatewho").fill("ops.night")
        page.locator("#gateok").click()
        expect(page.locator(".toast.ok").last).to_contain_text("EOD_COMPLETE", timeout=8000)
        shot("07_eod_segregation")
    step("T7 EOD: payments agent refused · recon agent + ops.night runs it", t7)

    def t8():
        page.locator("#vfy").click()
        expect(page.locator("#vres")).to_have_text("⛓ VALID", timeout=8000)
        shot("08_chain_valid")
    step("T8 Verify chain → ⛓ VALID after the whole session", t8)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"cbs_portal_e2e.webm")
    print(f"\nvideo: {ART/'cbs_portal_e2e.webm'}")

report={"suite":"MockBank teller portal — recorded E2E",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
