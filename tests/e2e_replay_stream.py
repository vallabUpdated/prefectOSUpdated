"""E2E: opening the orchestrator mid-run replays everything that already happened.

Backend-only counterpart to e2e_parallel_runs.py — no browser needed. Drives the
stubbed-LLM server (tests/e2e_stub_server.py, port 5056) through one full run and
asserts the guarantees the dashboard relies on:

  1. a viewer attached from the start sees the run live;
  2. a viewer attached halfway through receives the *entire* backlog first,
     then follows along live (nothing is stolen from the first viewer);
  3. a viewer resuming from a sequence number gets only what it missed;
  4. after the run ends, its events.jsonl replays the run from disk — which is
     what lets a dashboard opened after a server restart still show the history;
  5. /live-runs advertises the run so a freshly loaded dashboard finds it.

Usage:
    python tests/e2e_stub_server.py          # in one terminal
    python tests/e2e_replay_stream.py        # in another
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:5056"
TMP_PROJECTS = Path(__file__).resolve().parent / ".e2e_tmp" / "projects"


# ── tiny HTTP/SSE helpers ────────────────────────────────────────────────────

def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode())


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as res:
        return json.loads(res.read().decode())


class Viewer(threading.Thread):
    """One dashboard attached to /stream/<run_id>, collecting what it receives."""

    def __init__(self, run_id: str, from_seq: int = 0, name: str = "viewer"):
        super().__init__(daemon=True, name=name)
        self.run_id, self.from_seq = run_id, from_seq
        self.events: list[dict] = []
        self.error: str | None = None
        self.ended = threading.Event()

    def run(self) -> None:
        url = f"{BASE}/stream/{self.run_id}?from={self.from_seq}"
        try:
            with urllib.request.urlopen(url, timeout=180) as res:
                for raw in res:
                    line = raw.decode("utf-8").strip()
                    if not line.startswith("data:"):
                        continue
                    data = json.loads(line[5:].strip())
                    if data.get("type") == "heartbeat":
                        continue
                    self.events.append(data)
                    if data.get("type") == "stream_end":
                        break
        except Exception as exc:                                      # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.ended.set()

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]

    def seqs(self) -> list[int]:
        return [e["seq"] for e in self.events if "seq" in e]

    def wait_for(self, type_: str, timeout: float = 60.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for e in self.events:
                if e["type"] == type_:
                    return e
            if self.ended.is_set():
                return None
            time.sleep(0.1)
        return None


def approve_gates(run_id: str, viewer: Viewer, stop: threading.Event) -> None:
    """Approve every gate the run opens, until it ends."""
    approved = 0
    while not stop.is_set() and not viewer.ended.is_set():
        pending = [e for e in list(viewer.events) if e["type"] == "approval_required"]
        if len(pending) > approved:
            approved += 1
            try:
                post(f"/approve/{run_id}", {"decision": "approve"})
            except Exception as exc:                                  # noqa: BLE001
                print(f"  ! approve failed: {exc}")
        time.sleep(0.2)


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f" — {detail}" if detail and not ok else ""))
    return ok


def main() -> int:
    try:
        get("/live-runs")
    except urllib.error.URLError:
        print("Stub server not reachable on :5056 — start it with "
              "`python tests/e2e_stub_server.py` first.")
        return 2

    print("Starting a run …")
    run_id = post("/run", {"activity": "replay smoke test app"})["run_id"]
    print(f"  run_id = {run_id}")

    early = Viewer(run_id, name="early")
    early.start()

    stop = threading.Event()
    approver = threading.Thread(target=approve_gates, args=(run_id, early, stop), daemon=True)
    approver.start()

    # Let the run build up some history before the "second window" opens.
    if early.wait_for("approval_required", timeout=60) is None:
        print("  ! run never reached a gate"); return 1
    time.sleep(3)
    backlog_at_attach = len(early.events)

    print(f"Attaching a second viewer after {backlog_at_attach} events …")
    late = Viewer(run_id, name="late")
    late.start()
    resume = Viewer(run_id, from_seq=backlog_at_attach, name="resume")
    resume.start()

    early.ended.wait(timeout=240)
    late.ended.wait(timeout=30)
    resume.ended.wait(timeout=30)
    stop.set()

    ok = True
    print("\nChecks:")
    ok &= check("early viewer streamed the run", not early.error and "pipeline_completed" in early.types(),
                early.error or f"types={early.types()[-5:]}")
    ok &= check("late viewer got the full backlog from seq 1",
                late.seqs()[:1] == [1] and len(late.events) >= backlog_at_attach,
                f"first={late.seqs()[:3]} count={len(late.events)} vs backlog={backlog_at_attach}")
    ok &= check("late viewer saw the same events as the early one",
                late.seqs() == early.seqs(),
                f"early={len(early.seqs())} late={len(late.seqs())}")
    ok &= check("early viewer lost nothing to the late one (no event stealing)",
                early.seqs() == sorted(set(early.seqs())) and len(early.seqs()) == len(late.seqs()))
    ok &= check("resuming viewer got only what it missed",
                bool(resume.seqs()) and min(resume.seqs()) > backlog_at_attach,
                f"first={resume.seqs()[:3]} (expected > {backlog_at_attach})")
    ok &= check("sequence numbers are gapless",
                early.seqs() == list(range(1, len(early.seqs()) + 1)),
                f"got {early.seqs()[:10]}…")
    ok &= check("gate decisions are broadcast to every viewer",
                "approval_decided" in late.types())

    # 4 — durable replay off disk (what survives a server restart)
    from run_events import replay_from_disk
    project = next((e.get("project_dir") for e in early.events
                    if e["type"] == "project_created"), None)
    disk = replay_from_disk(project) if project else []
    live_seqs = early.seqs()          # includes stream_end, which is a recorded event
    ok &= check("events.jsonl replays the whole run",
                [e["seq"] for e in disk] == live_seqs,
                f"disk={len(disk)} live={len(live_seqs)}")

    # 5 — a past run is streamable by project id, and advertised to new dashboards
    project_id = Path(project).name if project else ""
    past = Viewer(project_id, name="past")
    past.start()
    past.ended.wait(timeout=30)
    ok &= check("a finished run streams from disk by project id",
                not past.error and [e["seq"] for e in past.events if "seq" in e] == [e["seq"] for e in disk],
                past.error or f"got {len(past.events)} events")

    advertised = {r["run_id"] for r in get("/live-runs").get("runs", [])}
    ok &= check("/live-runs advertises the run to a freshly opened dashboard",
                run_id in advertised, f"advertised={sorted(advertised)}")

    print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
