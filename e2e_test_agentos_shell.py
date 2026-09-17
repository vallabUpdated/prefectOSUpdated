"""Recorded E2E: two-layer Agent OS shell.
Layer 1: OS home with industry tiles + OS-wide signed log.
Layer 2: industry workspaces (SAP agents + filtered log; Banking with
'Open Banking workspace' that lands on the existing loan product).
Video + shots → e2e_artifacts_shell/."""
import json, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE="http://127.0.0.1:8000"; ART=Path("e2e_artifacts_shell"); ART.mkdir(exist_ok=True)
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
    shot=lambda n: page.screenshot(path=str(ART/f"{n}.png"), full_page=True)

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        page.get_by_text("Launch Workspace Demo").click()
        page.locator(".ln-item", has_text="Agent OS").click()
        expect(page.locator(".aos-title")).to_contain_text("Agent OS")
        expect(page.locator(".aos-tile")).to_have_count(5)
        expect(page.locator(".aos-tile.active")).to_have_count(3)
        shot("01_os_home_layer1")
    step("T1 LAYER 1 — OS home: 5 industry tiles, 3 installed", t1)

    def t2():
        tile = page.locator(".aos-tile", has_text="SAP")
        expect(tile).to_contain_text("2 agents governed")
        tile.click()
        expect(page.locator(".aos-ind-title")).to_have_text("SAP workspace")
        expect(page.locator(".aos-crumb-here")).to_contain_text("SAP")
        expect(page.locator(".gv-card")).to_have_count(2)
        shot("02_sap_workspace_layer2")
    step("T2 LAYER 2 — SAP workspace: breadcrumb, 2 agents", t2)

    def t3():
        deny = page.locator(".gv-rec", has_text="LFA1.bank_account").first
        expect(deny).to_be_visible()
        expect(deny).to_contain_text("call_denied")
        recs = page.locator(".gv-rec").all_inner_texts()
        assert not any("email_classifier" in r for r in recs), "banking leaked into SAP log"
        shot("03_sap_filtered_log")
    step("T3 SAP log is industry-scoped: fraud denial in, banking events out", t3)

    def t4():
        page.locator(".aos-back").click()
        expect(page.locator(".aos-tile")).to_have_count(5)
        page.locator(".aos-tile", has_text="Banking").click()
        expect(page.locator(".aos-ind-title")).to_have_text("Banking workspace")
        expect(page.locator(".gv-card", has_text="email_classifier")).to_be_visible()
        shot("04_banking_workspace")
    step("T4 back to OS home → Banking workspace opens with its agents", t4)

    def t5():
        page.locator(".aos-app-btn", has_text="Open Banking workspace").click()
        expect(page.get_by_text("Loan Processing Suite")).to_be_visible(timeout=10000)
        shot("05_banking_app_is_existing_product")
    step("T5 'Open Banking workspace' lands on the existing loan product — the product is Banking's app on the OS", t5)

    def t6():
        page.locator(".ln-item", has_text="Agent OS").click()
        ins = page.locator(".aos-tile", has_text="Insurance")
        expect(ins).to_contain_text("3 agents ready to install")
        ins.locator(".aos-switch").click()
        expect(ins).to_contain_text("agents governed", timeout=8000)
        shot("06_insurance_installed_from_home")
    step("T6 Insurance installed from the OS home tile — live, receipted", t6)

    def t7():
        v = ctx.request.get(BASE+"/governance/verify").json()
        assert v["valid"], v
    step("T7 one signed chain across both layers verifies VALID", t7)

    page.wait_for_timeout(1200)
    vp=page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"agentos_shell_e2e.webm")
    print(f"\nvideo: {ART/'agentos_shell_e2e.webm'}")

report={"suite":"Agent OS two-layer shell — recorded E2E",
        "passed":sum(1 for _,s,_ in results if s=="PASS"),
        "failed":sum(1 for _,s,_ in results if s!="PASS"),
        "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
