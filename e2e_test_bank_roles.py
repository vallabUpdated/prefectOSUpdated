"""Recorded E2E: 8 banking scenarios with ADMIN and NORMAL-USER logins.
MockBank Branch Console over BankCore (SQLite) behind the PrefectOS
gateway. Roles: admin = approver (sees all modules, can approve gates);
teller1 = operator (limited nav, cannot approve). Policy still outranks
role: even admin cannot unlock the beneficiary fraud path.
Video + shots → e2e_artifacts_roles/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:9100"; ART=Path("e2e_artifacts_roles"); ART.mkdir(exist_ok=True)
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

    def s1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        page.locator("#lu").fill("teller1"); page.locator("#lp").fill("wrongpass")
        page.locator("#lgo").click()
        expect(page.locator("#lerr")).to_be_visible()
        shot("01_bad_password_rejected")
        page.locator("#lp").fill("teller123"); page.locator("#lgo").click()
        expect(page.locator("#userchip")).to_contain_text("S. Kaur")
        expect(page.locator("#userchip")).to_contain_text("operator")
    step("S1 login: wrong password rejected · teller1 signs in as OPERATOR", s1)

    def s2():
        expect(page.locator(".acct")).to_have_count(4, timeout=10000)
        for v in ("Onboarding","Beneficiaries","EOD"):
            expect(page.locator(".nav-btn", has_text=v)).to_be_hidden()
        expect(page.locator(".nav-btn", has_text="Cash")).to_be_visible()
        shot("02_operator_limited_nav")
    step("S2 operator sees dashboard + Cash/Payments only — admin modules hidden", s2)

    def s3():
        page.locator(".nav-btn", has_text="Cash").click()
        page.locator("#cashgo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        expect(page.locator("#gaterole")).to_be_visible()          # "only an admin can approve"
        expect(page.locator("#gateok")).to_be_hidden()             # no Approve button for operator
        shot("03_operator_cannot_approve")
        page.locator("#gateno").click()
        expect(page.locator(".toast.hold").last).to_contain_text("rejected at the human gate", timeout=8000)
    step("S3 operator's cash txn gates · Approve is NOT offered to operator · stays held", s3)

    def s4():
        page.locator("#lout").click(); page.wait_for_load_state("networkidle")
        page.locator("#lu").fill("admin"); page.locator("#lp").fill("admin123")
        page.locator("#lgo").click()
        expect(page.locator("#userchip")).to_contain_text("A. Verma")
        expect(page.locator("#userchip")).to_contain_text("approver")
        for v in ("Onboarding","Beneficiaries","EOD"):
            expect(page.locator(".nav-btn", has_text=v)).to_be_visible()
        shot("04_admin_full_nav")
    step("S4 logout → admin signs in as APPROVER · all modules visible", s4)

    def s5():
        page.locator(".nav-btn", has_text="Cash").click()
        page.locator("#cashgo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        expect(page.locator("#gatewho")).to_have_value("admin")    # approver auto-filled = login id
        page.locator("#gateok").click()
        expect(page.locator(".toast.ok").last).to_contain_text("POSTED", timeout=8000)
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct", has_text="SB100301")).to_contain_text("98,000", timeout=10000)
        shot("05_admin_approves_cash")
    step("S5 admin cash ₹10,000: approver auto-filled from login → POSTED → ₹98,000", s5)

    def s6():
        page.locator(".nav-btn", has_text="Payments").click()
        page.locator("#agent").select_option("cbs.payments_agent")
        page.locator("#paygo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        page.locator("#gateok").click()
        expect(page.locator(".toast.ok").last).to_contain_text("POSTED", timeout=8000)
        page.locator(".nav-btn", has_text="Dashboard").click()
        expect(page.locator(".acct", has_text="SB100101")).to_contain_text("2,95,000", timeout=10000)
        expect(page.locator(".rec", has_text="by admin").first).to_be_visible()
        shot("06_admin_transfer_double_entry")
    step("S6 admin approves ₹50,000 transfer · double entry lands · receipt names 'admin'", s6)

    def s7():
        page.locator(".nav-btn", has_text="Beneficiaries").click()
        page.locator("#benedit").click()
        expect(page.locator(".toast.deny").last).to_contain_text("Blocked by policy", timeout=8000)
        expect(page.locator("#benac")).to_have_text("UTIB000123456")
        shot("07_policy_outranks_admin")
    step("S7 EVEN ADMIN cannot change beneficiary bank a/c — policy outranks role", s7)

    def s8():
        page.locator(".nav-btn", has_text="EOD").click()
        page.locator("#agent").select_option("cbs.recon_agent")
        page.locator("#eodgo").click()
        expect(page.locator("#gate.on")).to_be_visible(timeout=8000)
        page.locator("#gateok").click()
        expect(page.locator(".toast.ok").last).to_contain_text("EOD_COMPLETE", timeout=8000)
        page.locator("#vfy").click()
        expect(page.locator("#vres")).to_have_text("⛓ VALID", timeout=8000)
        shot("08_eod_and_chain_valid")
    step("S8 admin runs EOD via recon agent → interest posted → chain ⛓ VALID", s8)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"bank_roles_e2e.webm")
    print(f"\nvideo: {ART/'bank_roles_e2e.webm'}")

report={"suite":"MockBank admin vs operator — 8 recorded scenarios",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
