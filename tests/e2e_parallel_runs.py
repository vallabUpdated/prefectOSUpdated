"""Playwright E2E: two parallel pipeline runs in the real dashboard (stub LLM).

Prerequisites:
    pip install playwright        # uses the system Edge/Chrome, no download
    python tests/e2e_stub_server.py   # in another terminal (port 5056)

Then:
    python tests/e2e_parallel_runs.py             # headless
    python tests/e2e_parallel_runs.py --headed    # watch it in a real browser window

Starts two runs, verifies the run switcher, pauses/resumes run 2 while run 1
keeps going, auto-approves every gate on both runs, and asserts both complete
with fully isolated on-disk artifacts. Screenshots land in
tests/.e2e_tmp/shots/.
"""
import json, shutil, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(__file__).resolve().parent / ".e2e_tmp"
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:5056"
SHOTS = TMP / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)
E2E_PROJECTS = TMP / "projects"
if E2E_PROJECTS.exists():
    shutil.rmtree(E2E_PROJECTS)
E2E_PROJECTS.mkdir(parents=True)

ACTIVITY_1 = "Build a python CLI tool that prints a greeting message (E2E parallel test run one)"
ACTIVITY_2 = "Build a python script that computes fibonacci numbers (E2E parallel test run two)"

# gates per run: (agent_file + output) x (plan, spec, env, execute, test)
GATES_PER_RUN = 10


HEADED = "--headed" in sys.argv


def launch_browser(p):
    # slow_mo in headed mode so a human can follow the clicks
    opts = {"headless": not HEADED, "slow_mo": 200 if HEADED else 0}
    for kwargs in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
        try:
            return p.chromium.launch(**opts, **kwargs)
        except Exception:
            continue
    raise RuntimeError("No Chromium-based browser available")


def chip_statuses(page):
    chips = page.locator(".run-chip")
    return [chips.nth(i).locator(".rc-status").inner_text().strip() for i in range(chips.count())]


def select_chip(page, i):
    page.locator(".run-chip").nth(i).click()
    page.wait_for_timeout(120)


def status_text(page):
    return page.locator("#status-text").inner_text().strip()


checks = []

def check(name, ok, detail=""):
    checks.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        raise AssertionError(name + ": " + detail)


with sync_playwright() as p:
    browser = launch_browser(p)
    page = browser.new_page(viewport={"width": 1680, "height": 950})
    page.goto(BASE, wait_until="networkidle")

    page.get_by_role("button", name="Live run", exact=True).click()

    # ── Start run 1 ──────────────────────────────────────────────────────
    page.fill("#prompt", ACTIVITY_1)
    page.click("#run-btn")
    page.wait_for_selector("#status-text:has-text('running'), #status-text:has-text('awaiting')", timeout=10000)
    check("run 1 started", True)

    # ── Start run 2 in parallel ──────────────────────────────────────────
    page.fill("#prompt", ACTIVITY_2)
    run_btn_label = page.locator("#run-btn span").inner_text()
    check("run button offers parallel start", "new" in run_btn_label.lower(), run_btn_label)
    page.click("#run-btn")
    page.wait_for_selector("#run-switcher", timeout=10000)
    page.wait_for_function("document.querySelectorAll('.run-chip').length === 2", timeout=10000)
    check("run switcher shows 2 runs", True, " / ".join(chip_statuses(page)))
    page.screenshot(path=str(SHOTS / "01_two_runs_started.png"))

    approvals = [0, 0]

    # ── Board view: all live runs side by side ───────────────────────────
    page.click("#view-toggle")
    page.wait_for_selector("#run-board", timeout=5000)
    cards = page.locator(".run-card:not(.new-run-card)")
    check("board shows a card per run", cards.count() == 2, str(cards.count()))
    check("board has a start-another-run card", page.locator(".new-run-card").count() == 1)
    for i in range(2):  # inline-approve the current gate straight from each card
        card = cards.nth(i)
        card.locator(".rc-approve").wait_for(state="visible", timeout=10000)
        card.locator(".rc-approve").click()
        approvals[i] += 1
        page.wait_for_timeout(150)
    check("inline card approvals accepted", True, str(approvals))
    page.screenshot(path=str(SHOTS / "01b_board_view.png"))
    page.click("#view-toggle")  # back to single-run detail view
    page.wait_for_selector("#left", timeout=5000)

    # ── Pause run 2, verify run 1 unaffected ─────────────────────────────
    select_chip(page, 1)
    page.wait_for_selector("#pause-pipeline-btn.visible", timeout=10000)
    page.click("#pause-pipeline-btn")
    page.wait_for_selector("#status-text:has-text('paused')", timeout=10000)
    check("run 2 paused", status_text(page) == "paused", status_text(page))

    select_chip(page, 0)
    s1 = status_text(page)
    check("run 1 not affected by run 2 pause", s1 != "paused", s1)

    select_chip(page, 1)
    check("run 2 still paused after switching back", status_text(page) == "paused")
    page.screenshot(path=str(SHOTS / "02_run2_paused_run1_running.png"))

    page.click("#pause-pipeline-btn")  # now "▶ Resume"
    page.wait_for_function("!document.querySelector('#status-text').textContent.includes('paused')", timeout=10000)
    check("run 2 resumed", True, status_text(page))

    # ── Approve every gate on both runs until both complete ─────────────
    deadline = time.time() + 300
    mid_shot_taken = False
    while time.time() < deadline:
        statuses = chip_statuses(page)
        if len(statuses) == 2 and all(s == "completed" for s in statuses):
            break
        for i in range(2):
            select_chip(page, i)
            approve = page.locator(".btn-approve")
            if approve.count() and approve.is_visible():
                approve.click()
                approvals[i] += 1
                page.wait_for_timeout(120)
        if not mid_shot_taken and min(approvals) >= 4:
            page.screenshot(path=str(SHOTS / "03_mid_run_approvals.png"))
            mid_shot_taken = True
        page.wait_for_timeout(250)

    statuses = chip_statuses(page)
    check("both runs completed", statuses == ["completed", "completed"],
          f"statuses={statuses} approvals={approvals}")
    check("run 1 went through all gates", approvals[0] == GATES_PER_RUN, str(approvals[0]))
    check("run 2 went through all gates", approvals[1] == GATES_PER_RUN, str(approvals[1]))

    # ── Verify per-run isolation of outputs (on disk) ────────────────────
    chips = page.locator(".run-chip")
    titles = {chips.nth(i).get_attribute("title") for i in range(2)}
    check("switcher chips carry distinct activities", titles == {ACTIVITY_1, ACTIVITY_2}, str(titles))

    projects = sorted(d for d in E2E_PROJECTS.iterdir() if d.is_dir())
    check("exactly 2 project dirs created", len(projects) == 2, str([d.name for d in projects]))
    manifests = {json.loads((d / "project.json").read_text(encoding="utf-8"))["activity"] for d in projects}
    check("each run wrote its own manifest", manifests == {ACTIVITY_1, ACTIVITY_2})
    for d in projects:
        has_src = any(d.rglob("main.py")) and (d / "plan.md").exists() and (d / "spec.md").exists()
        check(f"{d.name} has plan/spec/sources", has_src)
        from decision_ledger import verify_file
        ok_ledger, n_entries, err = verify_file(d / "decision_ledger.jsonl")
        check(f"{d.name} ledger chain verifies", ok_ledger, err or f"{n_entries} entries")

    page.screenshot(path=str(SHOTS / "04_both_completed.png"))

    browser.close()

print(f"\nALL {len(checks)} CHECKS PASSED")
