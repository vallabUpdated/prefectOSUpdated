"""Recorded E2E: BankCore (SQLite, Finacle-like) behind the PrefectOS
governance gateway, driven through the MockBank Branch Console.
On camera: customer onboarding + account opening through the human gate,
gated cash deposit, double-entry transfer with statement proof, the
beneficiary fraud denial, EOD interest posting, DB persistence across a
full page reload, and chain verification.
Video + shots → e2e_artifacts_bank/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:9100"; ART=Path("e2e_artifacts_bank"); ART.mkdir(exist_ok=True)
results=[]
def step(name,fn):
    t0=time.time()
    try: fn(); results.append((name,"PASS",round(time.time()-t0,2))); print(f"  PASS  {name}")
    except Exception as e:
        results.append((name,f"FAIL: {str(e)[:110]}",round(time.time()-t0,2)))
        print(f"  FAIL  {name}: {e}"); raise

def approve(page, who):
    expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
    page.locator("#gatewho").fill(who)
    page.locator("#gateok").click()

with sync_playwright() as p:
    browser=p.chromium.launch()
    ctx=browser.new_context(viewport={"width":1280,"height":800},
        record_video_dir=str(ART/"video"), record_video_size={"width":1280,"height":800})
    page=ctx.new_page()
    shot=lambda n: page.screenshot(path=str(ART/f"{n}.png"), full_page=True)
    state={}

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        expect(page.locator(".brand")).to_contain_text("MockBank")
        expect(page.locator(".acct")).to_have_count(4, timeout=10000)
        expect(page.locator(".acct", has_text="SB100101")).to_contain_text("R. Sharma")
        shot("01_dashboard_4_db_accounts")
    step("T1 console loads · 4 accounts straight from the SQLite core", t1)

    def t2():
        page.locator(".nav-btn", has_text="Onboarding").click()
        page.locator("#agent").select_option("cbs.onboarding_agent")
        page.locator("#cname").fill("N. Rao")
        page.locator("#cifgo").click()
        shot("02_cif_gate_modal")
        approve(page, "onboarding.head")
        toast = page.locator(".toast.ok").last
        expect(toast).to_contain_text("CIF_CREATED", timeout=8000)
        state["cif"] = toast.inner_text().split("CIF_CREATED · ")[1].split(" ·")[0].strip()
    step("T2 create customer N. Rao → gated → CIF issued by the DB", t2)

    def t3():
        page.locator("#acif").fill(state["cif"])
        page.locator("#acctgo").click()
        approve(page, "onboarding.head")
        toast = page.locator(".toast.ok").last
        expect(toast).to_contain_text("ACCT_OPENED", timeout=8000)
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct")).to_have_count(5, timeout=10000)
        expect(page.locator(".acct", has_text="N. Rao")).to_contain_text("25,000")
        shot("03_fifth_account_opened")
    step("T3 open SBGEN ₹25,000 for the new CIF → 5th card on dashboard", t3)

    def t4():
        page.locator(".nav-btn", has_text="Cash").click()
        page.locator("#agent").select_option("cbs.teller_agent")
        page.locator("#cashgo").click()
        approve(page, "branch.supervisor")
        expect(page.locator(".toast.ok").last).to_contain_text("POSTED", timeout=8000)
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct", has_text="SB100301")).to_contain_text("98,000", timeout=10000)
        shot("04_cash_deposit_posted")
    step("T4 teller cash deposit ₹10,000 → gated → SB100301 now ₹98,000", t4)

    def t5():
        page.locator(".nav-btn", has_text="Payments").click()
        page.locator("#agent").select_option("cbs.payments_agent")
        page.locator("#paygo").click()
        approve(page, "r.mehta")
        expect(page.locator(".toast.ok").last).to_contain_text("POSTED", timeout=8000)
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct", has_text="SB100101")).to_contain_text("2,95,000", timeout=10000)
        expect(page.locator(".acct", has_text="CA200201")).to_contain_text("17,80,000")
        shot("05_double_entry_both_sides_moved")
    step("T5 ₹50,000 transfer → BOTH legs move: SB +50k, CA −50k (double entry)", t5)

    def t6():
        page.locator(".acct", has_text="SB100101").click()
        expect(page.locator("#stwrap table")).to_be_visible(timeout=8000)
        row = page.locator("#stwrap tr", has_text="TRANSFER")
        expect(row).to_contain_text("CR")
        expect(row).to_contain_text("50,000")
        shot("06_statement_shows_transfer")
    step("T6 statement of SB100101 shows the TRANSFER CR entry from the DB", t6)

    def t7():
        page.locator(".nav-btn", has_text="Beneficiaries").click()
        page.locator("#benedit").click()
        expect(page.locator(".toast.deny").last).to_contain_text("Blocked by policy", timeout=8000)
        expect(page.locator("#benac")).to_have_text("UTIB000123456")
        shot("07_fraud_path_blocked")
    step("T7 beneficiary bank change → denied · row untouched in the DB", t7)

    def t8():
        page.locator(".nav-btn", has_text="EOD Batch").click()
        page.locator("#agent").select_option("cbs.recon_agent")
        page.locator("#eodgo").click()
        approve(page, "ops.night")
        expect(page.locator(".toast.ok").last).to_contain_text("EOD_COMPLETE", timeout=8000)
        shot("08_eod_interest_posted")
    step("T8 EOD run by recon agent → SB interest accrual posted to the book", t8)

    def t9():
        page.reload(); page.wait_for_load_state("networkidle")
        expect(page.locator(".acct")).to_have_count(5, timeout=10000)
        expect(page.locator(".acct", has_text="N. Rao")).to_be_visible()
        expect(page.locator(".acct", has_text="SB100301")).to_contain_text("98,0")
        shot("09_reload_db_persists")
    step("T9 full page reload → everything persists (it's a real database)", t9)

    def t10():
        page.locator("#vfy").click()
        expect(page.locator("#vres")).to_have_text("⛓ VALID", timeout=8000)
        expect(page.locator(".rec", has_text="by ops.night").first).to_be_visible()
        shot("10_chain_valid")
    step("T10 receipt chain ⛓ VALID over the entire session", t10)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"bankcore_e2e.webm")
    print(f"\nvideo: {ART/'bankcore_e2e.webm'}")

report={"suite":"BankCore (SQLite) behind PrefectOS — recorded E2E",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
