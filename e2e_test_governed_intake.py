"""Recorded E2E: email intake WITH the governance layer plugged in.

Every Process click now flows through the deny-by-default Governor:
allowed queues gate on the human click (which feeds earned autonomy),
and the KYC queue — deliberately absent from the agent's policy — is
refused live in the UI. Video + screenshots + report to e2e_artifacts2/.
"""
import json, re, subprocess, time
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8000"
ART = Path("e2e_artifacts2"); ART.mkdir(exist_ok=True)
results = []

def step(name, fn):
    t0 = time.time()
    try:
        fn(); results.append((name, "PASS", round(time.time()-t0,2))); print(f"  PASS  {name}")
    except Exception as e:
        results.append((name, f"FAIL: {str(e)[:110]}", round(time.time()-t0,2)))
        print(f"  FAIL  {name}: {e}"); raise

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width":1280,"height":800},
        record_video_dir=str(ART/"video"),
        record_video_size={"width":1280,"height":800})
    ctx.add_init_script("""
        localStorage.setItem('prefectos_user_id','e2e-sarah');
        localStorage.setItem('prefectos_user_name','Sarah Jenkins');
        localStorage.setItem('prefectos_user_email','sarah@imperial.example');
        localStorage.setItem('prefectos_user_role','approver');""")
    page = ctx.new_page()
    shot = lambda n: page.screenshot(path=str(ART/f"{n}.png"))

    def t1():
        page.goto(BASE); page.wait_for_load_state("networkidle")
        page.get_by_text("Launch Workspace Demo").click()
        expect(page.get_by_text("Loan Processing Suite")).to_be_visible(timeout=10000)
        expect(page.locator(".pw-email-banner")).to_contain_text("3 emailed document pack")
        shot("01_three_pending_banner")
    step("T1 app opens · banner shows 3 pending packs", t1)

    def t2():
        page.locator(".pw-email-banner button").click()
        expect(page.locator(".ei-row")).to_have_count(3)
        shot("02_intake_list_3")
    step("T2 intake list shows 3 packs (2 loan, 1 KYC)", t2)

    def t3():
        page.locator(".ei-row", has_text="4412").click()
        expect(page.locator(".ei-doc")).to_have_count(4)
        page.get_by_role("button", name=re.compile("Process 4 documents")).click()
        done = page.locator(".ei-done")
        expect(done).to_be_visible(timeout=10000)
        expect(done).to_contain_text("batch_")
        shot("03_loan_processed_through_gate")
    step("T3 loan pack processes — Process click satisfies the governance gate", t3)

    def t4():
        recs = [json.loads(l) for l in
                Path("project_output/agent_governance/receipts.jsonl").read_text().splitlines()]
        events = [r["event"] for r in recs]
        assert "call_gated" in events, events
        outcome = [r for r in recs if r["event"] == "outcome"][-1]
        assert outcome["outcome"] == "approved", outcome
        assert outcome["approver"] == "Sarah Jenkins", outcome
        auto = json.loads(Path("project_output/agent_governance/autonomy.json").read_text())
        assert auto["email_batch_processor"]["approved"] == 1, auto
    step("T4 governance receipts: call_gated → approved by Sarah · trust ladder +1", t4)

    def t5():
        page.locator(".ei-row", has_text="KYC pack").click()
        expect(page.locator(".ei-doc")).to_have_count(2)
        shot("04_kyc_pack_open")
        page.get_by_role("button", name=re.compile("Process 2 documents")).click()
        err = page.locator(".ei-err")
        expect(err).to_be_visible(timeout=10000)
        expect(err).to_contain_text("governance denied")
        expect(err).to_contain_text("not_in_allowlist")
        shot("05_GOVERNANCE_DENIAL_ON_SCREEN")
    step("T5 KYC pack: Process click DENIED by policy, live in the UI", t5)

    def t6():
        intakes = ctx.request.get(BASE+"/email/intake").json()["intakes"]
        kyc = [i for i in intakes if "KYC" in i["subject"]][0]
        assert kyc["status"] == "pending", kyc     # denial did NOT consume the pack
        recs = [json.loads(l) for l in
                Path("project_output/agent_governance/receipts.jsonl").read_text().splitlines()]
        deny = [r for r in recs if r["event"] == "call_denied"][-1]
        assert deny["reason"] == "not_in_allowlist", deny
        assert deny["resource"] == "acme_sfb::kyc", deny
    step("T6 KYC intake still pending · denial receipted (acme_sfb::kyc)", t6)

    def t7():
        for tool, chain in (("agent_governance.py","governance receipts"),
                            ("email_ingest.py","email audit")):
            out = subprocess.run(["python3", tool, "--verify" if tool.startswith("agent") else "--verify-audit"],
                                 capture_output=True, text=True,
                                 env={**__import__("os").environ})
            assert "VALID" in out.stdout, f"{chain}: {out.stdout}{out.stderr}"
    step("T7 BOTH chains verify VALID: signed governance receipts + email audit", t7)

    page.wait_for_timeout(1200)
    vp = page.video.path(); ctx.close(); browser.close()
    Path(vp).rename(ART/"governed_intake_e2e.webm")
    print(f"\nvideo: {ART/'governed_intake_e2e.webm'}")

report = {"suite":"PrefectOS governed email intake — recorded E2E",
          "passed":sum(1 for _,s,_ in results if s=="PASS"),
          "failed":sum(1 for _,s,_ in results if s!="PASS"),
          "steps":[{"name":n,"status":s,"secs":t} for n,s,t in results]}
(ART/"report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report["steps"], indent=2))
