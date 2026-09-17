"""Recorded E2E: OS-first landing page.
Hero pitches the Operating System for AI Agents; the industries strip is
the OS's layer-2 entry — SAP chip lands in the Agent OS console, Banking
chip lands in the loan workspace. Video + shots → e2e_artifacts_landing/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:8000"; ART=Path("e2e_artifacts_landing"); ART.mkdir(exist_ok=True)
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
    ctx.add_init_script("""
        localStorage.setItem('prefectos_user_id','e2e-sarah');
        localStorage.setItem('prefectos_user_name','Sarah Jenkins');
        localStorage.setItem('prefectos_user_role','approver');""")
    page=ctx.new_page()
    shot=lambda n: page.screenshot(path=str(ART/f"{n}.png"), full_page=False)

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        expect(page.locator(".light-hero-title")).to_contain_text("The Operating System")
        expect(page.locator(".light-hero-title")).to_contain_text("AI Agents")
        expect(page.locator(".light-hero-subtitle")).to_contain_text("One governance spine")
        shot("01_os_first_hero")
    step("T1 landing hero: 'The Operating System for AI Agents'", t1)

    def t2():
        expect(page.locator(".os-industries-label")).to_have_text("INDUSTRIES ON THE OS")
        expect(page.locator(".os-ind-chip")).to_have_count(5)
        shot("02_industries_strip")
    step("T2 industries strip: 5 chips (Banking · Insurance · SAP · Salesforce · Software Dev)", t2)

    def t3():
        page.locator(".os-ind-chip", has_text="SAP").click()
        expect(page.locator(".aos-title")).to_contain_text("Agent OS", timeout=10000)
        expect(page.locator(".aos-tile")).to_have_count(5)
        shot("03_sap_chip_lands_in_os")
    step("T3 SAP chip → straight into the Agent OS console", t3)

    def t4():
        page.locator(".aos-tile", has_text="SAP").click()
        expect(page.locator(".aos-ind-title")).to_have_text("SAP workspace")
        shot("04_layer2_sap")
        page.locator(".aos-back").click()
    step("T4 layer 2 reachable: SAP workspace from OS home", t4)

    def t5():
        page.get_by_text("Landing page").click()
        expect(page.locator(".os-ind-chip").first).to_be_visible(timeout=10000)
        page.locator(".os-ind-chip", has_text="Banking").click()
        expect(page.get_by_text("Loan Processing Suite")).to_be_visible(timeout=10000)
        shot("05_banking_chip_lands_in_loan_suite")
    step("T5 back to landing → Banking chip → loan workspace (Banking's app)", t5)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"landing_os_e2e.webm")
    print(f"\nvideo: {ART/'landing_os_e2e.webm'}")

report={"suite":"OS-first landing — recorded E2E",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
