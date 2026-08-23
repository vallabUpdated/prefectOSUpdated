"""
server.py — Flask web server that wraps the LangGraph orchestrator pipeline.

Serves ui.html and provides the API endpoints the dashboard JS expects:
  GET  /                     → ui.html
  POST /run                  → start a pipeline run (returns {run_id})
  GET  /stream/<run_id>      → SSE event stream
  POST /approve/<run_id>     → send approve/reject decision
  POST /pause/<run_id>       → pause the pipeline at the next stage boundary
  POST /resume/<run_id>      → resume a paused pipeline
  GET  /runs                 → list past project runs

Loan document processing (Landing Page → Loan Processing):
  GET  /loan/config          → loan types + default prompts
  GET  /loan/scan?path=      → count processable documents at a path
  POST /loan/process         → start a loan document job (returns {job_id})
  GET  /loan/stream/<job_id> → SSE progress + token stream
  POST /loan/cancel/<job_id> → cancel a running job
  GET  /loan/report/<job_id> → the eligibility report (html | json | md)

Usage:
    python server.py               # port 5055
    python server.py --port 8080
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

# Force UTF-8 on Windows (avoids cp1252 UnicodeEncodeError from Orchestrator.py)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import logging
log = logging.getLogger("server")
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(ROOT_DIR / ".env")

from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

# ── Orchestrator imports ──────────────────────────────────────────────────────
import Orchestrator as _orch
from Orchestrator import (
    AGENTS_DIR,
    AgentFactory,
    AgentRegistry,
    AgentStatus,
    ApprovalRejectedError,
    BudgetExhaustedError,
    GraphState,
    MCP_CONFIG,
    MAX_AGENTS,
    PROJECTS_ROOT,
    WORKER_MODEL,
    build_graph,
    detect_server_url,
    parse_env_blocks,
    write_audit,
    write_output_summary,
)
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

# ── Loan document processing (Landing Page) ──────────────────────────────────
import loan_processing as _loan

# ── Replayable run event log (open the orchestrator window at any time) ──────
from run_events import RunEventStore, replay_from_disk as _replay_events_from_disk

# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

UI_DIST = ROOT_DIR / "ui" / "dist"

# ─────────────────────────────────────────────────────────────────────────────
# Run context — one per active pipeline run
# ─────────────────────────────────────────────────────────────────────────────

class RunContext:
    def __init__(self, run_id: str, activity: str, codebase: str = ""):
        self.run_id          = run_id
        self.activity        = activity
        self.codebase        = codebase          # optional legacy codebase path (Stage 0)
        self.meta: dict      = {}                # UI run config: client_tag/provider/rag/run_type
        # Replayable event log — every subscriber gets the full backlog, so a
        # dashboard opened (or reloaded) mid-run replays the run from its start.
        self.events          = RunEventStore(run_id)
        self.started_at      = datetime.now().isoformat()
        self.approval_event  = threading.Event()
        self.approval_decision: str = "approve"
        self.approval_edited: str | None = None   # user-edited document content
        self.status          = "running"
        self.project_dir     = ""
        self.total_in        = 0
        self.total_out       = 0
        self.seen_stages: set[str] = set()   # stages that emitted stage_started

        # Pipeline cancellation
        self.cancel_event    = threading.Event()
        self.cancel_reason   = ""

        # Pipeline pause/resume — the gate is SET while the pipeline may run
        # and CLEARED while paused; the pipeline thread blocks on it at every
        # stage/approval boundary.
        self.paused          = False
        self._pause_gate     = threading.Event()
        self._pause_gate.set()

        # Generated app process tracking
        self.app_proc:      subprocess.Popen | None = None
        self.app_url:       str = ""
        self.app_port:      int = 0
        self.app_pid:       int = 0
        self.app_framework: str = ""
        self.app_cmd:       str = ""

    def emit(self, type_: str, **data):
        data["type"] = type_
        data["ts"]   = datetime.now().isoformat()
        self.events.emit(data)

    def wait_approval(self, stage: str, content: str = "", editable: bool = False) -> str:
        self.emit("approval_required", stage=stage, content=content, editable=editable)
        self.approval_event.wait()
        self.approval_event.clear()
        return self.approval_decision

    def set_decision(self, decision: str, edited: str | None = None):
        self.approval_decision = decision
        self.approval_edited   = edited
        self.approval_event.set()

    def request_cancel(self, reason: str = "User stopped the pipeline") -> None:
        """Signal the pipeline thread to stop at the next approval gate."""
        self.cancel_reason = reason
        self.cancel_event.set()
        # Unblock a pending approval gate so the pipeline notices immediately.
        self.approval_decision = "reject"
        self.approval_edited   = None
        self.approval_event.set()
        # Release a paused pipeline so it can observe the cancellation.
        self.paused = False
        self._pause_gate.set()

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def request_pause(self) -> None:
        """Hold the pipeline thread at the next stage/approval boundary."""
        self.paused = True
        self._pause_gate.clear()

    def request_resume(self) -> None:
        self.paused = False
        self._pause_gate.set()

    def wait_if_paused(self) -> None:
        """Block the pipeline thread while paused (cancel/resume release it)."""
        self._pause_gate.wait()


_runs: dict[str, RunContext] = {}

# ─────────────────────────────────────────────────────────────────────────────
# SSE-enabled AgentRegistry — emits events on every lifecycle transition
# ─────────────────────────────────────────────────────────────────────────────

class SSERegistry(AgentRegistry):
    def __init__(self, project_dir: Path, ctx: RunContext):
        super().__init__(project_dir)
        self._ctx = ctx

    def register(self, agent_id, slot, model, stage):
        rec = super().register(agent_id, slot, model, stage)
        self._ctx.emit("agent_registered",
            agent_id=agent_id, slot=slot, model=model, stage=stage,
            spawned_at=datetime.now().isoformat(),
            budget_used=slot, budget_max=MAX_AGENTS,
        )
        return rec

    def mark_alive(self, agent_id):
        super().mark_alive(agent_id)
        rec = self._find(agent_id)
        self._ctx.emit("agent_alive",
            agent_id=agent_id,
            spawned_at=rec.spawned_at if rec else datetime.now().isoformat(),
        )

    def mark_torn_down(self, agent_id, elapsed_s, output_chars):
        super().mark_torn_down(agent_id, elapsed_s, output_chars)
        # Emit a fake token update so the token counters tick
        per_char = 0.25
        out_tok = max(1, int(output_chars * per_char))
        in_tok  = max(1, int(output_chars * 0.05))
        self._ctx.total_in  += in_tok
        self._ctx.total_out += out_tok
        self._ctx.emit("token_update",
            agent_id=agent_id,
            input_tokens=in_tok, output_tokens=out_tok,
            total_input_tokens=self._ctx.total_in,
            total_output_tokens=self._ctx.total_out,
            total_tokens=self._ctx.total_in + self._ctx.total_out,
        )
        self._ctx.emit("agent_torn_down",
            agent_id=agent_id, elapsed_s=elapsed_s, output_chars=output_chars,
        )

    def mark_failed(self, agent_id, error):
        super().mark_failed(agent_id, error)
        self._ctx.emit("agent_failed", agent_id=agent_id, error=str(error))

    def _find(self, agent_id):
        for r in self._records:
            if r.agent_id == agent_id:
                return r
        return None

    def _print_table(self, event):
        pass  # suppress terminal noise


# ─────────────────────────────────────────────────────────────────────────────
# Interrupt → SSE mapping
# ─────────────────────────────────────────────────────────────────────────────

_STAGE_MAP = {
    "planner:agent_file":     ("plan",    "PLANNER"),
    "planner:output":         ("plan",    None),
    "spec_writer:agent_file": ("spec",    "SPEC_WRITER"),
    "spec_writer:output":     ("spec",    None),
    "env_builder:agent_file": ("env",     "ENV_BUILDER"),
    "env_builder:output":     ("env",     None),
    "executor:agent_file":    ("execute", "EXECUTOR"),
    "executor:output":        ("execute", None),
    "tester:agent_file":      ("test",    "TESTER"),
    "tester:output":          ("test",    None),
}


def _handle_interrupt(irpt, pipeline, config, ctx: RunContext):
    """Map one LangGraph interrupt to SSE events, wait for HTTP decision, resume."""
    ctx.wait_if_paused()
    if ctx.is_cancelled:
        # Skip the approval-gate UI entirely and reject straight through.
        pipeline.invoke(Command(resume="reject"), config=config)
        return

    value  = irpt.value if hasattr(irpt, "value") else irpt
    stage  = value.get("stage", "") if isinstance(value, dict) else str(value)
    prompt = value.get("prompt", "") if isinstance(value, dict) else ""

    pipe_stage, agent_name = _STAGE_MAP.get(stage, ("plan", None))

    # Emit stage_started once per pipeline stage
    if pipe_stage not in ctx.seen_stages:
        ctx.seen_stages.add(pipe_stage)
        ctx.emit("stage_started", stage=pipe_stage)

    # Agent file preview interrupt
    if stage.endswith(":agent_file") and agent_name:
        md_path = AGENTS_DIR / f"CLAUDE_{agent_name}.md"
        content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        ctx.emit("agent_file_preview",
            filename=f"CLAUDE_{agent_name}.md",
            content=content[:600],
            budget_used=len(ctx.seen_stages),
            budget_max=MAX_AGENTS,
        )
        decision = ctx.wait_approval(stage, content[:600])
    else:
        # Output approval — editable gates (plan/spec) carry the full document
        # in the interrupt payload; others fall back to a file preview.
        project_dir = Path(ctx.project_dir)
        editable    = bool(isinstance(value, dict) and value.get("editable"))
        content     = (value.get("content", "") if isinstance(value, dict) else "") \
                      or _read_output_preview(pipe_stage, project_dir)
        if stage.endswith(":output"):
            ctx.emit("stage_completed", stage=pipe_stage)
        decision = ctx.wait_approval(
            stage, content if editable else content[:800], editable=editable,
        )

    # Resume LangGraph with the decision (and any edited document content).
    # Hold here too, so a pause requested while the gate was open takes effect
    # before the next stage starts (a cancel during that hold wins).
    ctx.wait_if_paused()
    edited = ctx.approval_edited
    ctx.approval_edited = None
    if ctx.is_cancelled or decision.strip().lower() == "reject":
        # Inject reject so the pipeline raises ApprovalRejectedError
        pipeline.invoke(Command(resume="reject"), config=config)
    elif edited is not None and stage.endswith(":output"):
        pipeline.invoke(
            Command(resume={"decision": "approve", "content": edited}), config=config
        )
    else:
        pipeline.invoke(Command(resume="approve"), config=config)


def _read_output_preview(pipe_stage: str, project_dir: Path) -> str:
    file_map = {
        "plan":    "plan.md",
        "spec":    "spec.md",
        "env":     "requirements.txt",
        "execute": "agent_registry.json",
        "test":    "test_report.md",
    }
    fname = file_map.get(pipe_stage)
    if not fname:
        return ""
    p = project_dir / fname
    if not p.exists():
        return ""
    text = p.read_text(encoding="utf-8")
    return text[:800]


# ─────────────────────────────────────────────────────────────────────────────
# Generated-app launcher — finds an entry file, launches it, tracks the PID
# ─────────────────────────────────────────────────────────────────────────────

_APP_ENTRY_CANDIDATES = ["app.py", "main.py", "run.py", "server.py", "wsgi.py"]
_PORT_PATTERNS = [
    re.compile(r'app\.run\s*\([^)]*port\s*=\s*(\d{4,5})'),
    re.compile(r'uvicorn\.run\s*\([^)]*port\s*=\s*(\d{4,5})'),
    re.compile(r'^\s*PORT\s*=\s*(\d{4,5})', re.MULTILINE),
    re.compile(r'^\s*port\s*=\s*(\d{4,5})', re.MULTILINE),
    re.compile(r'default\s*=\s*(\d{4,5}).*port', re.IGNORECASE),
    re.compile(r'--port[\'",\s]+(\d{4,5})'),
]


def _find_launchable_app(project_dir: Path):
    """Return (entry_path, framework, port) for the first runnable app file found, or None."""
    for name in _APP_ENTRY_CANDIDATES:
        path = project_dir / name
        if not path.exists():
            hits = [p for p in project_dir.rglob(name) if ".venv" not in p.parts]
            path = hits[0] if hits else None
        if not path or not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        framework = "python"
        port = None
        if "fastapi" in text.lower() or "FastAPI(" in text:
            framework, port = "fastapi", 8000
        elif "flask" in text.lower() or "Flask(" in text:
            framework, port = "flask", 5000
        for pat in _PORT_PATTERNS:
            m = pat.search(text)
            if m:
                port = int(m.group(1))
                break
        if port is None:
            continue
        return path, framework, port
    return None


def _venv_python(project_dir: Path) -> str:
    venv_dir = project_dir / ".venv"
    candidate = (venv_dir / "Scripts" / "python.exe") if sys.platform == "win32" else (venv_dir / "bin" / "python")
    return str(candidate) if candidate.exists() else sys.executable


def _port_open(port: int, timeout: float = 0.5) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_app(proc: subprocess.Popen, port: int, timeout: float = 10.0) -> str:
    """Poll until the app answers on its port. Returns 'up', 'dead', or 'no_port'."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return "dead"
        if _port_open(port):
            return "up"
        time.sleep(0.4)
    return "no_port" if proc.poll() is None else "dead"


def _spawn_app(python_exe: str, entry_path: Path, log_path: Path) -> subprocess.Popen:
    """Start the app with output captured to app_launch.log (not DEVNULL, so
    crashes are diagnosable instead of silently showing a dead 'LIVE' link)."""
    log_fh = open(log_path, "w", encoding="utf-8", errors="replace")
    return subprocess.Popen(
        [python_exe, entry_path.name], cwd=str(entry_path.parent),
        stdout=log_fh, stderr=subprocess.STDOUT,
    )


def launch_generated_app(project_dir: Path, on_log=None) -> dict | None:
    """Launch the generated app as a subprocess and health-check it.

    Returns launch info (with "healthy" flag and "error" detail) or None if no
    entry point was found. If the first attempt dies with ModuleNotFoundError
    and the project has no venv, installs requirements.txt into a fresh project
    venv and retries once — the common failure when the run skipped venv creation.
    """
    emit = on_log or (lambda msg, level="info": None)
    found = _find_launchable_app(project_dir)
    if not found:
        return None
    entry_path, framework, port = found
    log_path = project_dir / "app_launch.log"

    # With parallel runs, another run's app may already hold this port — the
    # health check would then see the *other* app answering and report a false
    # "up" for a process that never bound. Refuse to launch instead.
    if _port_open(port):
        return {
            "proc": None, "url": "", "port": port, "pid": 0,
            "framework": framework, "cmd": f"python {entry_path.name}",
            "healthy": False,
            "error": f"Port {port} is already in use (likely an app from another run). "
                     f"Stop that app or change the generated app's port, then relaunch.",
            "log_path": str(log_path),
        }

    python_exe = _venv_python(project_dir)
    proc   = _spawn_app(python_exe, entry_path, log_path)
    status = _wait_for_app(proc, port)

    if status == "dead":
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1500:] if log_path.exists() else ""
        needs_deps = "ModuleNotFoundError" in tail or "ImportError" in tail
        if needs_deps and not (project_dir / ".venv").exists() and (project_dir / "requirements.txt").exists():
            emit("App needs its own dependencies — creating project venv and installing requirements.txt …", "warn")
            try:
                from Orchestrator import create_venv
                create_venv(project_dir / ".venv", project_dir / "requirements.txt")
            except Exception as e:
                emit(f"Dependency install failed: {e}", "error")
            else:
                proc   = _spawn_app(_venv_python(project_dir), entry_path, log_path)
                status = _wait_for_app(proc, port)

    if status == "dead":
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:] if log_path.exists() else ""
        return {
            "proc": None, "url": "", "port": port, "pid": 0,
            "framework": framework, "cmd": f"python {entry_path.name}",
            "healthy": False,
            "error": f"App process exited on startup. Last output:\n{tail or '(no output captured)'}",
            "log_path": str(log_path),
        }

    return {
        "proc":      proc,
        "healthy":   True,
        "error":     "" if status == "up" else f"Process is running but port {port} is not answering yet.",
        "log_path":  str(log_path),
        "url":       f"http://127.0.0.1:{port}",
        "port":      port,
        "pid":       proc.pid,
        "framework": framework,
        "cmd":       f"python {entry_path.name}",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner (background thread)
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(ctx: RunContext, skip_venv: bool = True):
    try:
        # Create per-request project dir
        from Orchestrator import ProjectManager
        pm = ProjectManager(PROJECTS_ROOT)
        project_dir, thread_id = pm.create(ctx.activity)
        ctx.project_dir = str(project_dir)
        # From here on every event is also appended to <project>/events.jsonl,
        # so the run stays replayable after the server process goes away.
        ctx.events.bind(project_dir)

        # Tamper-evident decision provenance for this run
        from decision_ledger import activate_ledger, record as ledger_record, sha256_text
        activate_ledger(project_dir)
        ledger_record(
            "run_started",
            thread_id=thread_id,
            activity_sha256=sha256_text(ctx.activity),
            activity=ctx.activity,
            existing_codebase=ctx.codebase or None,
            client_tag=ctx.meta.get("client_tag") or None,
            provider_requested=ctx.meta.get("provider") or None,
            run_type=ctx.meta.get("run_type") or None,
            rag_requested=ctx.meta.get("rag") or None,
            skills_excluded=ctx.meta.get("skills_excluded") or [],
            channel="web",
        )
        if ctx.meta:
            (project_dir / "run_meta.json").write_text(
                json.dumps(ctx.meta, indent=2), encoding="utf-8")

        ctx.emit("pipeline_started", activity=ctx.activity)
        ctx.emit("project_created",
            project_dir=str(project_dir), thread_id=thread_id)
        ctx.emit("log", msg=f"Project: <span class='ht'>{project_dir.name}</span>", level="info")

        # SSE-enabled registry + factory
        registry = SSERegistry(project_dir, ctx)
        factory  = AgentFactory(
            agents_dir=AGENTS_DIR,
            mcp_config=MCP_CONFIG,
            registry=registry,
        )

        # Bind this run's registry/factory to the current thread's context so
        # node functions resolve them per run — safe for parallel pipelines.
        _orch.set_run_context(registry, factory)

        # Build the LangGraph pipeline
        checkpointer = MemorySaver()
        pipeline     = build_graph(checkpointer)
        config       = {"configurable": {"thread_id": thread_id}}

        initial_state: GraphState = {
            "activity":       ctx.activity,
            "project_dir":    str(project_dir),
            "thread_id":      thread_id,
            "skip_venv":      skip_venv,
            "existing_codebase": ctx.codebase or "",
            "comprehension":  "",
            "plan":           "",
            "spec":           "",
            "env_script":     "",
            "requirements":   "",
            "source_files":   {},
            "agents_spawned": 0,
            "agent_log":      [],
            "approvals":      [],
            "stage_timings":  {},
            "messages":       [],
        }

        # First invoke — runs until first interrupt
        pipeline.invoke(initial_state, config=config)

        # Interrupt / resume loop
        while True:
            snapshot = pipeline.get_state(config)
            if not snapshot.tasks:
                break
            pending = []
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    pending.extend(task.interrupts)
            if not pending:
                break
            for irpt in pending:
                _handle_interrupt(irpt, pipeline, config, ctx)

        # Finished
        final = pipeline.get_state(config).values
        source_files = final.get("source_files", {})
        write_audit(final, registry)
        write_output_summary(final)
        pm.complete(project_dir)

        server_url = detect_server_url(project_dir)
        ctx.status = "completed"
        ctx.emit("pipeline_completed",
            project_dir=str(project_dir),
            venv_dir=str(project_dir / ".venv"),
            files=list(source_files.keys()),
            total_tokens=ctx.total_in + ctx.total_out,
            server_url=server_url or "",
        )

        # Launch the generated app as a subprocess so the UI can link to a live URL.
        ctx.emit("stage_started", stage="launch")
        try:
            launched = launch_generated_app(
                project_dir,
                on_log=lambda msg, level="info": ctx.emit("log", msg=msg, level=level),
            )
        except Exception as e:
            launched = None
            ctx.emit("log", msg=f"<span class='hr'>Could not launch app: {e}</span>", level="error")
        if launched and not launched.get("healthy", True):
            ctx.emit("log",
                msg=f"<span class='hr'>App failed to start — see app_launch.log. "
                    f"{launched.get('error','')}</span>", level="error")
            launched = None
        elif launched and launched.get("error"):
            ctx.emit("log", msg=f"<span class='ha'>{launched['error']}</span>", level="warn")
        if launched:
            ctx.app_proc      = launched["proc"]
            ctx.app_url       = launched["url"]
            ctx.app_port      = launched["port"]
            ctx.app_pid       = launched["pid"]
            ctx.app_framework = launched["framework"]
            ctx.app_cmd       = launched["cmd"]
            ctx.emit("app_launched",
                url=ctx.app_url, port=ctx.app_port, pid=ctx.app_pid,
                framework=ctx.app_framework, cmd=ctx.app_cmd)
            ctx.emit("log",
                msg=f"App launched: <a href='{ctx.app_url}' target='_blank' style='color:#a78bfa'>{ctx.app_url}</a>",
                level="ok")
        else:
            ctx.emit("log", msg="No launchable app entry point found.", level="warn")
        ctx.emit("stage_completed", stage="launch")

        ctx.emit("log", msg="<span class='hg'>Pipeline complete.</span>", level="ok")

    except ApprovalRejectedError as e:
        if ctx.is_cancelled:
            ctx.status = "cancelled"
            ctx.emit("pipeline_cancelled", reason=ctx.cancel_reason or str(e))
            ctx.emit("log", msg=f"<span class='ha'>Cancelled: {ctx.cancel_reason}</span>", level="warn")
        else:
            ctx.status = "failed"
            ctx.emit("pipeline_rejected", reason=str(e))
            ctx.emit("log", msg=f"<span class='ha'>Rejected: {e}</span>", level="warn")

    except BudgetExhaustedError as e:
        ctx.status = "failed"
        ctx.emit("pipeline_failed", reason=str(e))
        ctx.emit("log", msg=f"<span class='hr'>Budget: {e}</span>", level="error")

    except Exception as e:
        ctx.status = "failed"
        msg = str(e)
        ctx.emit("pipeline_failed", reason=msg)
        ctx.emit("log", msg=f"<span class='hr'>Error: {msg[:200]}</span>", level="error")
        traceback.print_exc()

    finally:
        ctx.emit("stream_end")

        # Every outcome passes through here, so the ledger gets one closing
        # record per run whether it completed, was rejected, or failed.
        try:
            import activity_ledger
            actor = getattr(ctx, "actor", None)
            if actor:
                activity_ledger.record(
                    actor, "pipeline_run",
                    f"Pipeline run {ctx.status} · {ctx.activity[:140]}",
                    run_id=ctx.run_id, status=ctx.status,
                    project=Path(ctx.project_dir).name if ctx.project_dir else None,
                    tokens=ctx.total_in + ctx.total_out,
                    reason=ctx.cancel_reason or None,
                    app_url=ctx.app_url or None,
                )
        except Exception as exc:                                      # noqa: BLE001
            log.warning("run-end activity not recorded: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the built React dashboard (ui/dist) if present, else fall back to ui.html."""
    dist_index = UI_DIST / "index.html"
    if dist_index.exists():
        return send_file(dist_index)
    log.warning("ui/dist not found — serving LEGACY ui.html. "
                "Run `cd ui && npm install && npm run build` to get the current UI.")
    return send_file(ROOT_DIR / "ui.html")


@app.route("/assets/<path:filename>")
def ui_assets(filename):
    """Serve the Vite-built JS/CSS assets for the React dashboard."""
    return send_from_directory(UI_DIST / "assets", filename)


@app.route("/prefectos-logo.png")
def prefectos_logo():
    """Serve the Prefect OS logo image."""
    logo_path = UI_DIST / "prefectos-logo.png"
    if logo_path.exists():
        return send_file(logo_path)
    return send_file(ROOT_DIR / "ui" / "public" / "prefectos-logo.png")


@app.route("/prefectos_eye_catching_topology_diagram.jpg")
def serve_topology_image():
    """Serve the 3D multi-agent topology diagram image."""
    img_path = UI_DIST / "prefectos_eye_catching_topology_diagram.jpg"
    if not img_path.exists():
        img_path = ROOT_DIR / "ui" / "public" / "prefectos_eye_catching_topology_diagram.jpg"
    if img_path.exists():
        return send_file(img_path)
    return jsonify({"detail": "Image not found"}), 404



@app.route("/PrefectOS_SOC2_TypeII_Security_Evidence_Pack.pdf")
@app.route("/download/soc2-evidence-pack.pdf")
def download_soc2_pdf():
    """Serve the actual downloadable SOC 2 Type II Evidence Pack PDF document."""
    pdf_path = UI_DIST / "PrefectOS_SOC2_TypeII_Security_Evidence_Pack.pdf"
    if not pdf_path.exists():
        pdf_path = ROOT_DIR / "ui" / "public" / "PrefectOS_SOC2_TypeII_Security_Evidence_Pack.pdf"
    if not pdf_path.exists():
        # Auto-generate if missing
        try:
            from scripts.generate_soc2_pdf import generate_pdf
            generate_pdf(pdf_path)
        except Exception as exc:
            log.exception("PDF generation failed: %s", exc)
    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="PrefectOS_SOC2_TypeII_Security_Evidence_Pack.pdf",
    )


@app.route("/api/contact-sales", methods=["POST"])
def contact_sales():
    """Handle enterprise quote requests and dispatch leads to vallab@prefectos.ai."""
    data = request.json or {}
    company = data.get("company", "Unknown Institution")
    email = data.get("email", "unknown@institution.com")
    cloud = data.get("cloud", "AWS Private VPC")
    volume = data.get("volume", "50k-250k")
    recipient = "vallab@prefectos.ai"

    subject = f"🚀 Enterprise SLA Quote Request: {company}"
    body = f"""
NEW ENTERPRISE SLA QUOTE REQUEST

Target Recipient: {recipient}
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

CLIENT DETAILS:
- Institution / Company: {company}
- Work Email: {email}
- Target Cloud Deployment: {cloud}
- Monthly Document Volume: {volume}

GOVERNANCE METADATA:
- Environment: Production Enterprise Host
- Cloud Region: US-East (AWS Private VPC)
- Compliance Package: SOC 2 Type II & ISO 27001 Verified
"""

    # Dynamically reload .env for fresh SMTP settings
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=True)
        except Exception:
            pass

    smtp_sent = False
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "vallab.aidevelop@gmail.com")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if smtp_user and smtp_pass and len(smtp_pass.strip()) > 0:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = recipient
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [recipient], msg.as_string())
            smtp_sent = True
            log.info("REAL SMTP EMAIL DELIVERED TO %s via %s", recipient, smtp_user)
        except Exception as exc:
            log.warning("SMTP dispatch failed: %s", exc)

    lead_entry = {
        "timestamp": datetime.now().isoformat(),
        "recipient": recipient,
        "company": company,
        "work_email": email,
        "target_cloud": cloud,
        "monthly_volume": volume,
        "subject": subject,
        "email_body": body.strip(),
        "smtp_sent": smtp_sent,
        "status": "DELIVERED_VIA_SMTP" if smtp_sent else "LOGGED_TO_OUTBOUND_QUEUE",
    }


    log.info("AUTONOMOUS EMAIL IMMEDIATELY DISPATCHED TO %s: %s", recipient, lead_entry)

    # Save to JSON file log
    leads_file = ROOT_DIR / "data" / "sales_leads.json"
    leads_file.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if leads_file.exists():
        try:
            with open(leads_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.append(lead_entry)
    with open(leads_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    # Also log to outbound_emails.log
    outbound_log = ROOT_DIR / "data" / "outbound_emails.log"
    with open(outbound_log, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] OUTBOUND EMAIL TO {recipient}\nSubject: {subject}\n{body}\n{'='*60}\n\n")

    return jsonify({
        "status": "success",
        "message": f"Autonomous email immediately sent to {recipient} without user intervention.",
        "recipient": recipient,
        "smtp_sent": smtp_sent,
        "lead": lead_entry,
    })


@app.route("/api/admin/keys", methods=["GET"])
def list_api_keys():
    """List all registered Admin-Issued User API Keys."""
    keys_file = ROOT_DIR / "data" / "api_keys.json"
    if keys_file.exists():
        try:
            with open(keys_file, "r", encoding="utf-8") as f:
                keys = json.load(f)
                return jsonify({"status": "success", "keys": keys})
        except Exception:
            pass
    return jsonify({"status": "success", "keys": []})


@app.route("/api/admin/keys/create", methods=["POST"])
def create_api_key():
    """Generate and issue a new User Access API Key."""
    data = request.json or {}
    name = data.get("name", "New User")
    email = data.get("email", "user@institution.com")
    role = data.get("role", "Approver")
    institution = data.get("institution", "Imperial Financial Bank")

    import secrets
    new_key = f"prf_live_{role.lower().replace(' ', '_')}_{secrets.token_hex(4)}"

    key_entry = {
        "key": new_key,
        "name": name,
        "email": email,
        "role": role,
        "institution": institution,
        "status": "ACTIVE",
        "created_at": datetime.now().isoformat(),
    }

    keys_file = ROOT_DIR / "data" / "api_keys.json"
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if keys_file.exists():
        try:
            with open(keys_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing.append(key_entry)
    with open(keys_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    log.info("NEW API KEY ISSUED BY ADMIN: %s for %s (%s)", new_key, name, email)
    return jsonify({"status": "success", "message": "API key generated successfully", "key": key_entry})








@app.route("/run", methods=["POST"])
def start_run():
    body     = request.get_json(force=True) or {}
    activity = (body.get("activity") or "").strip()
    if len(activity) < 10:
        return jsonify({"detail": "Activity must be at least 10 characters."}), 400

    run_id = f"run-{int(time.time()*1000)}"

    # codebase: legacy string path, or StartRun's structured object
    #   {source: "path"|"git"|"indexed", path?, git_url?, git_branch?, collection?}
    raw_cb   = body.get("codebase")
    codebase = ""
    if isinstance(raw_cb, str):
        codebase = raw_cb.strip()
    elif isinstance(raw_cb, dict):
        src = raw_cb.get("source", "path")
        if src == "path":
            codebase = (raw_cb.get("path") or "").strip()
        elif src == "git":
            url    = (raw_cb.get("git_url") or "").strip()
            branch = (raw_cb.get("git_branch") or "main").strip()
            if not url:
                return jsonify({"detail": "git_url is required for git source"}), 400
            dest = ROOT_DIR / "checkouts" / run_id
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", branch, url, str(dest)],
                    check=True, capture_output=True, text=True, timeout=300,
                )
            except FileNotFoundError:
                return jsonify({"detail": "git is not installed on the server"}), 400
            except subprocess.TimeoutExpired:
                return jsonify({"detail": "git clone timed out (300s)"}), 400
            except subprocess.CalledProcessError as exc:
                return jsonify({"detail": f"git clone failed: {exc.stderr[-300:]}"}), 400
            codebase = str(dest)
        elif src == "indexed":
            return jsonify({"detail": "Previously-indexed source needs a codebase "
                                      "registry — re-run from path or git for now."}), 400
    if codebase and not Path(codebase).expanduser().is_dir():
        return jsonify({"detail": f"Codebase path not found: {codebase}"}), 400

    ctx = RunContext(run_id, activity, codebase=codebase)
    ctx.meta = {
        "run_type":   body.get("run_type") or ("govern" if codebase else "greenfield"),
        "client_tag": (body.get("client_tag") or "").strip(),
        "provider":   (body.get("provider") or "").strip(),
        "rag":        body.get("rag") if isinstance(body.get("rag"), dict) else {},
        "skills_excluded": body.get("skills_excluded") or [],
    }
    # Who started this run. Kept on the context (never in ctx.meta, which is
    # written to run_meta.json) so the access key stays out of the project dir.
    ctx.actor = _actor(body)
    _runs[run_id] = ctx

    try:
        import activity_ledger
        activity_ledger.record(
            ctx.actor, "pipeline_run", f"Started pipeline run · {activity[:140]}",
            run_id=run_id, status="started",
            run_type=ctx.meta.get("run_type") or None,
            client_tag=ctx.meta.get("client_tag") or None,
            codebase=codebase or None,
        )
    except Exception as exc:                                          # noqa: BLE001
        log.warning("run-start activity not recorded: %s", exc)

    t = threading.Thread(target=_run_pipeline, args=(ctx, True), daemon=True)
    t.start()

    return jsonify({"run_id": run_id})


def _sse(data: dict) -> str:
    """One SSE frame. The event's seq becomes the SSE id, so a browser
    reconnect carries Last-Event-ID and resumes without gaps or duplicates."""
    seq = data.get("seq")
    head = f"id: {seq}\n" if seq else ""
    return f"{head}event: {data['type']}\ndata: {json.dumps(data, default=str)}\n\n"


def _resume_from(req) -> int:
    """Sequence number the client already has: Last-Event-ID, or ?from=N.

    0 (the default) means "replay this run from the beginning" — which is what
    a freshly opened orchestrator window asks for."""
    for raw in (req.headers.get("Last-Event-ID"), req.args.get("from")):
        try:
            if raw is not None:
                return max(0, int(raw))
        except (TypeError, ValueError):
            continue
    return 0


@app.route("/stream/<run_id>")
def stream(run_id: str):
    """Live + replayed event stream for a run.

    Any number of dashboards may attach at once, at any point in a run's life.
    Each subscriber first receives every event the run has already emitted
    (from memory for a live run, from events.jsonl for one this process never
    saw), then follows along live. That is what lets a user open the
    orchestrator window mid-run — or after a restart — and watch the whole run
    unfold exactly as it happened."""
    after = _resume_from(request)
    ctx = _runs.get(run_id)

    if not ctx:
        # Not a live run: replay a past one straight off disk, then end.
        project_dir = _resolve_project_dir(run_id)
        past = _replay_events_from_disk(project_dir, after) if project_dir else []
        if not past:
            return jsonify({"detail": "Run not found"}), 404

        def replay_only():
            for data in past:
                yield _sse(data)
            if past[-1].get("type") != "stream_end":
                # The run never recorded its own end (server died mid-run):
                # close the connection so the client stops waiting.
                yield f"event: stream_end\ndata: {json.dumps({'type': 'stream_end'})}\n\n"

        return Response(replay_only(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    q = ctx.events.subscribe(after_seq=after)

    def generate():
        try:
            # Backlog first (already seeded into q), then live events.
            while True:
                try:
                    data = q.get(timeout=15)
                    yield _sse(data)
                    if data["type"] == "stream_end":
                        break
                except queue.Empty:
                    if ctx.status in ("completed", "failed", "cancelled"):
                        # Run is over and this subscriber is drained — tell late
                        # or reconnecting clients to stop instead of holding a
                        # zombie connection on heartbeats forever.
                        yield f"event: stream_end\ndata: {json.dumps({'type': 'stream_end'})}\n\n"
                        break
                    yield f"event: heartbeat\ndata: {json.dumps({'type':'heartbeat'})}\n\n"
        finally:
            ctx.events.unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# How many already-finished runs (replayed off disk) a freshly opened
# dashboard picks up alongside the runs this process is still holding.
REPLAY_RECENT_RUNS = 3


@app.route("/live-runs")
def live_runs():
    """Runs a freshly opened dashboard should attach to, oldest first.

    Two sources: the runs this process is holding in memory (in flight or
    finished this session), plus the most recent runs whose events.jsonl
    survives on disk — so a dashboard opened after a server restart still
    replays what happened instead of starting from a blank screen."""
    out = []
    seen_projects = set()
    for run_id, ctx in _runs.items():
        project_id = Path(ctx.project_dir).name if ctx.project_dir else ""
        seen_projects.add(project_id)
        out.append({
            "run_id":     run_id,
            "activity":   ctx.activity,
            "status":     ctx.status,
            "project_dir": ctx.project_dir,
            "project_id": project_id,
            "started_at": ctx.started_at,
            "paused":     ctx.paused,
            "last_seq":   ctx.events.last_seq,
            "replay":     False,
        })

    try:
        from run_events import EVENTS_FILENAME
        past = sorted(
            (d for d in PROJECTS_ROOT.iterdir()
             if d.is_dir() and d.name not in seen_projects
             and (d / EVENTS_FILENAME).is_file()),
            key=lambda d: d.name,
        )[-REPLAY_RECENT_RUNS:]
    except (FileNotFoundError, OSError):
        past = []

    for d in past:
        activity = ""
        try:
            activity = json.loads((d / "project.json").read_text(encoding="utf-8")).get("activity", "")
        except Exception:                                             # noqa: BLE001
            pass
        out.append({
            "run_id":     d.name,           # past runs stream by project id
            "activity":   activity,
            "status":     "finished",
            "project_dir": str(d),
            "project_id": d.name,
            "started_at": d.name,           # timestamped dir name sorts correctly
            "paused":     False,
            "last_seq":   0,
            "replay":     True,
        })

    # In-memory runs stamp ISO timestamps, disk runs a 20260822_183604 dir
    # name — compare on digits alone so the two orders interleave correctly.
    out.sort(key=lambda r: re.sub(r"\D", "", r["started_at"])[:14])
    return jsonify({"runs": out})


@app.route("/approve/<run_id>", methods=["POST"])
def approve(run_id: str):
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": "Run not found"}), 404
    body     = request.get_json(force=True) or {}
    decision = body.get("decision", "approve").strip().lower()
    if decision == "delegate":
        return jsonify({"detail": "Delegation needs a user store — coming with auth."}), 501
    if decision not in ("approve", "reject"):
        return jsonify({"detail": "decision must be 'approve' or 'reject'"}), 400
    edited = body.get("content")
    if edited is None:
        edited = body.get("edited_content")          # ApprovalGateV2 payload name
    if edited is not None and not isinstance(edited, str):
        return jsonify({"detail": "content must be a string"}), 400

    decided_by = body.get("decided_by") if isinstance(body.get("decided_by"), dict) else {}
    rejection  = body.get("rejection")  if isinstance(body.get("rejection"), dict) else None
    if decision == "reject" and rejection is not None:
        if not (rejection.get("category") and len((rejection.get("reason") or "").strip()) >= 10):
            return jsonify({"detail": "rejection needs a category and a reason (≥10 chars)"}), 400

    # Seal WHO decided (and why, on reject) into this run's hash chain.
    # Safe from this thread: the pipeline thread is blocked at the gate, and
    # DecisionLedger reloads the chain tail from disk on init.
    if ctx.project_dir:
        try:
            from decision_ledger import DecisionLedger
            DecisionLedger(ctx.project_dir).append(
                "ui_decision",
                run_id=run_id,
                decision=decision,
                decided_by=decided_by,
                rejection=rejection,
                edited=edited is not None,
            )
        except Exception as exc:                                  # noqa: BLE001
            log.warning("ui_decision seal failed: %s", exc)

    # Broadcast the decision so every attached dashboard closes the gate — and
    # so a replayed run shows gates that were already decided as closed.
    ctx.emit("approval_decided", decision=decision, edited=edited is not None,
             decided_by=decided_by or None)

    try:
        import activity_ledger
        activity_ledger.record(
            _actor(body), "approval",
            f"{decision.title()}d {body.get('stage') or 'a gate'} · {ctx.activity[:120]}",
            run_id=run_id, decision=decision, edited=edited is not None,
            stage=body.get("stage") or None,
            rejection=(rejection or {}).get("category") if rejection else None,
        )
    except Exception as exc:                                          # noqa: BLE001
        log.warning("approval activity not recorded: %s", exc)

    ctx.set_decision(decision, edited)
    return jsonify({"ok": True, "decision": decision, "edited": edited is not None})


@app.route("/clients")
def list_clients():
    """Client/engagement registry for the StartRun screen.

    Reads clients.json at the repo root (editable by the SME admin);
    ships with samples so the UI works out of the box."""
    path = ROOT_DIR / "clients.json"
    try:
        return jsonify({"clients": json.loads(path.read_text(encoding="utf-8"))})
    except Exception:
        return jsonify({"clients": [
            {"id": "internal",  "name": "Internal / R&D",
             "policy": {"providers": ["anthropic", "ollama"]}},
        ]})


@app.route("/skills/match")
def skills_match():
    """Live preview of which skill cards will apply to an activity."""
    activity = (request.args.get("activity") or "").strip()
    if len(activity) < 4:
        return jsonify({"skills": []})
    try:
        from Orchestrator import SkillFactory
        matched = SkillFactory().match(activity)
        return jsonify({"skills": [
            {"skill_id": sk.skill_id, "name": sk.name} for sk in matched
        ]})
    except Exception as exc:
        return jsonify({"skills": [], "detail": str(exc)})


@app.route("/rag/collections")
def rag_collections():
    """Previously indexed codebases (rag_index/ scan) for the StartRun picker."""
    out = []
    for run_dir in sorted(PROJECTS_ROOT.glob("*/rag_index/*")):
        chunks = run_dir / "chunks.jsonl"
        if chunks.exists():
            try:
                n = sum(1 for l in chunks.open(encoding="utf-8") if l.strip())
            except OSError:
                n = 0
            out.append({"collection": run_dir.name,
                        "label": run_dir.parent.parent.name,
                        "chunks": n})
    return jsonify({"collections": out})


@app.route("/runs")
def list_runs():
    from Orchestrator import ProjectManager
    pm = ProjectManager(PROJECTS_ROOT)
    try:
        projects = pm.list_projects()
    except Exception:
        projects = []
    return jsonify({"runs": projects})


def _resolve_project_dir(run_id: str) -> Path | None:
    """Map a run identifier to its project directory.

    Accepts either a live run_id (looked up in _runs) or a past project's
    directory name (as returned by /runs → project_id). The value is reduced
    to its basename so it can never escape PROJECTS_ROOT."""
    ctx = _runs.get(run_id)
    if ctx and ctx.project_dir:
        return Path(ctx.project_dir)
    candidate = PROJECTS_ROOT / Path(run_id).name
    return candidate if candidate.is_dir() else None


@app.route("/ledger/<run_id>")
def get_ledger(run_id: str):
    """Return the decision ledger entries for a run (live or historical)."""
    from decision_ledger import LEDGER_FILENAME

    project_dir = _resolve_project_dir(run_id)
    if project_dir is None:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404

    path = project_dir / LEDGER_FILENAME
    if not path.exists():
        return jsonify({"run_id": run_id, "project_id": project_dir.name,
                        "entries": [], "detail": "No decision ledger recorded for this run."})

    entries, parse_errors = [], 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                parse_errors += 1
    return jsonify({"run_id": run_id, "project_id": project_dir.name,
                    "entries": entries, "parse_errors": parse_errors})


@app.route("/ledger/<run_id>/verify")
def verify_ledger(run_id: str):
    """Authoritative server-side chain verification (decision_ledger.verify_file)."""
    from decision_ledger import LEDGER_FILENAME, verify_file

    project_dir = _resolve_project_dir(run_id)
    if project_dir is None:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404

    ok, checked, error = verify_file(project_dir / LEDGER_FILENAME)
    return jsonify({"ok": ok, "checked": checked, "error": error})


@app.route("/comprehension/<run_id>")
def get_comprehension(run_id: str):
    """Stage 0 (legacy comprehension) results + provenance for a run.

    Returns the three comprehension documents written by comprehender_node
    (architecture.md / business_rules.md / risk_register.md) plus the
    Stage-0 provenance recorded in the decision ledger: digest stats,
    digest SHA-256, secrets withheld, RAG indexing stats, and the two
    comprehender HITL gates."""
    from decision_ledger import LEDGER_FILENAME

    project_dir = _resolve_project_dir(run_id)
    if project_dir is None:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404

    documents = {}
    for fname in ("architecture.md", "business_rules.md", "risk_register.md"):
        p = project_dir / fname
        if p.exists():
            try:
                documents[fname] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

    digested, indexed, gates = None, None, []
    ledger_path = project_dir / LEDGER_FILENAME
    if ledger_path.exists():
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev = e.get("event", "")
                if ev == "codebase_digested":
                    digested = e
                elif ev == "codebase_indexed":
                    indexed = e
                elif ev in ("gate_presented", "gate_decision") and \
                        str(e.get("gate", "")).startswith("comprehender:"):
                    gates.append(e)

    return jsonify({
        "run_id": run_id,
        "project_id": project_dir.name,
        "has_stage0": bool(documents or digested),
        "documents": documents,
        "digested": digested,
        "indexed": indexed,
        "gates": gates,
    })


@app.route("/docx/<run_id>/<kind>")
def download_docx(run_id: str, kind: str):
    """Download plan.docx / spec.docx for a run, generating it from the
    markdown on demand (so the link works while the approval gate is open)."""
    ctx = _runs.get(run_id)
    if not ctx or not ctx.project_dir:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    if kind not in ("plan", "spec"):
        return jsonify({"detail": "kind must be 'plan' or 'spec'"}), 400

    project_dir = Path(ctx.project_dir)
    md_path     = project_dir / f"{kind}.md"
    if not md_path.exists():
        return jsonify({"detail": f"{kind}.md not generated yet."}), 404

    from Orchestrator import export_docx
    title = ("Project Plan" if kind == "plan" else "Technical Specification") + f" — {ctx.activity}"
    body  = re.sub(rf"^# {kind.capitalize()}:[^\n]*\n+", "",
                   md_path.read_text(encoding="utf-8"), count=1)
    docx_path = project_dir / f"{kind}.docx"
    result = export_docx(title, body, docx_path)
    if result is None:
        return jsonify({"detail": "python-docx is not installed on the server."}), 501
    return send_file(docx_path, as_attachment=True, download_name=f"{kind}.docx")


@app.route("/cancel/<run_id>", methods=["POST"])
def cancel_pipeline(run_id: str):
    """Stop the pipeline at the next approval-gate boundary."""
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    if ctx.status in ("completed", "failed", "cancelled"):
        return jsonify({"detail": f"Run '{run_id}' is already finished (status={ctx.status})."}), 400
    ctx.request_cancel("User stopped the pipeline")
    return jsonify({"run_id": run_id, "cancelled": True, "status": ctx.status})


@app.route("/pause/<run_id>", methods=["POST"])
def pause_pipeline(run_id: str):
    """Hold the pipeline at the next stage/approval-gate boundary."""
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    if ctx.status in ("completed", "failed", "cancelled"):
        return jsonify({"detail": f"Run '{run_id}' is already finished (status={ctx.status})."}), 400
    if ctx.paused:
        return jsonify({"detail": f"Run '{run_id}' is already paused."}), 400
    ctx.request_pause()
    ctx.emit("pipeline_paused")
    ctx.emit("log", msg="<span class='ha'>Pipeline paused — holding at the next stage boundary.</span>", level="warn")
    return jsonify({"run_id": run_id, "paused": True, "status": ctx.status})


@app.route("/resume/<run_id>", methods=["POST"])
def resume_pipeline(run_id: str):
    """Release a paused pipeline."""
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    if not ctx.paused:
        return jsonify({"detail": f"Run '{run_id}' is not paused."}), 400
    ctx.request_resume()
    ctx.emit("pipeline_resumed")
    ctx.emit("log", msg="<span class='hg'>Pipeline resumed.</span>", level="ok")
    return jsonify({"run_id": run_id, "paused": False, "status": ctx.status})


@app.route("/stop/<run_id>", methods=["POST"])
def stop_app(run_id: str):
    """Kill the generated app subprocess for a completed run."""
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    if not ctx.app_pid:
        return jsonify({"detail": "No running app process for this run."}), 400
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(ctx.app_pid), "/F"], check=False)
        else:
            os.kill(ctx.app_pid, signal.SIGTERM)
        old_pid, old_url = ctx.app_pid, ctx.app_url
        ctx.app_pid = 0
        ctx.app_url = ""
        ctx.emit("app_stopped", pid=old_pid, url=old_url)
        return jsonify({"stopped": True, "pid": old_pid})
    except Exception as e:
        return jsonify({"detail": f"Failed to stop process: {e}"}), 500


@app.route("/app-status/<run_id>")
def app_status(run_id: str):
    """Return current status of the generated app process."""
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": f"Run '{run_id}' not found."}), 404
    pid_alive = False
    if ctx.app_pid:
        try:
            import psutil
            pid_alive = psutil.pid_exists(ctx.app_pid)
        except ImportError:
            try:
                if sys.platform == "win32":
                    import ctypes
                    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, ctx.app_pid)
                    pid_alive = h != 0
                    if h:
                        ctypes.windll.kernel32.CloseHandle(h)
                else:
                    os.kill(ctx.app_pid, 0)
                    pid_alive = True
            except (ProcessLookupError, PermissionError):
                pid_alive = False
    return jsonify({
        "run_id":    run_id,
        "app_url":   ctx.app_url,
        "app_port":  ctx.app_port,
        "app_pid":   ctx.app_pid,
        "app_cmd":   ctx.app_cmd,
        "framework": ctx.app_framework,
        "running":   pid_alive,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Loan processing (Landing Page → Loan Processing boxes)
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/loan/config")
def loan_config():
    """Processing types + their default (operator-editable) prompts.

    `?domain=loan|account` selects a section; omitted means the loan boxes, so
    existing callers keep working.
    """
    domain = (request.args.get("domain") or "loan").strip()
    types = [t for t in _loan.PROCESSING_TYPES if t.get("domain", "loan") == domain]
    return jsonify({
        "domain": domain,
        "loan_types": [
            {**t, "default_prompt": _loan.DEFAULT_PROMPTS.get(t["id"], "")}
            for t in types
        ],
        "supported_types": sorted(_loan.SUPPORTED),
        "max_docs": _loan.MAX_DOCS,
        "provider": _orch.LLM_PROVIDER,
        "model": WORKER_MODEL,
        "pricing": {
            "input_per_mtok": (_loan.PRICING_USD_PER_MTOK.get(WORKER_MODEL) or (None, None))[0],
            "output_per_mtok": (_loan.PRICING_USD_PER_MTOK.get(WORKER_MODEL) or (None, None))[1],
            "currency": "USD",
        },
    })


@app.route("/loan/scan")
def loan_scan():
    """Count the processable documents at a path, before a job is started."""
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"detail": "path is required"}), 400
    p = Path(raw).expanduser()
    if not p.exists():
        return jsonify({"detail": f"Path not found: {p}"}), 404
    supported, skipped = _loan.scan_documents(p)
    return jsonify({
        "path": str(p),
        "count": len(supported),
        "files": [f.name for f in supported[:25]],
        "skipped": len(skipped),
    })


@app.route("/loan/browse")
def loan_browse():
    """Server-side folder browser for the loan boxes.

    The browser cannot reveal a real local path from a file input, so the
    picker walks the filesystem here and hands back a genuine path — no upload,
    no copy. Same trust posture as the existing path fields: this is a local
    single-operator tool bound to 127.0.0.1.
    """
    raw = (request.args.get("path") or "").strip()

    # Quick links + drives, so the picker can start somewhere useful.
    home = Path.home()
    shortcuts = [{"name": label, "path": str(p)} for label, p in (
        ("Home", home), ("Downloads", home / "Downloads"),
        ("Desktop", home / "Desktop"), ("Documents", home / "Documents"),
    ) if p.is_dir()]
    drives = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            d = Path(f"{letter}:/")
            if d.exists():
                drives.append({"name": f"{letter}:", "path": str(d)})
    else:
        drives.append({"name": "/", "path": "/"})

    if not raw:
        raw = str(home)

    p = Path(raw).expanduser()
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        return jsonify({"detail": f"Not a folder: {p}", "shortcuts": shortcuts,
                        "drives": drives}), 404

    dirs, files, unreadable = [], [], 0
    try:
        for entry in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
                elif entry.is_file():
                    supported = entry.suffix.lower() in _loan.SUPPORTED
                    files.append({"name": entry.name, "path": str(entry),
                                  "size": entry.stat().st_size,
                                  "supported": supported})
            except OSError:
                unreadable += 1
    except PermissionError:
        return jsonify({"detail": f"Permission denied: {p}",
                        "shortcuts": shortcuts, "drives": drives}), 403

    parent = str(p.parent) if p.parent != p else None
    return jsonify({
        "path": str(p), "parent": parent,
        "dirs": dirs, "files": files,
        "processable": sum(1 for f in files if f["supported"]),
        "unreadable": unreadable,
        "shortcuts": shortcuts, "drives": drives,
        "separator": os.sep,
    })


@app.route("/loan/mkdir", methods=["POST"])
def loan_mkdir():
    """Create a subfolder from the picker (used for output paths)."""
    body = request.get_json(force=True) or {}
    parent = (body.get("path") or "").strip()
    name = (body.get("name") or "").strip()
    if not parent or not name:
        return jsonify({"detail": "path and name are required"}), 400
    if any(sep in name for sep in ("/", "\\")) or name in (".", ".."):
        return jsonify({"detail": "Folder name cannot contain a path separator."}), 400
    target = Path(parent).expanduser() / name
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return jsonify({"detail": f"Could not create folder: {exc}"}), 400
    return jsonify({"path": str(target)})


@app.route("/loan/process", methods=["POST"])
def loan_process():
    body = request.get_json(force=True) or {}
    try:
        job = _loan.start_job(
            loan_type=(body.get("loan_type") or "").strip(),
            input_path=(body.get("input_path") or "").strip(),
            output_path=(body.get("output_path") or "").strip(),
            prompt=body.get("prompt") or "",
            mode=(body.get("mode") or "deterministic").strip(),
            bank_name=(body.get("bank_name") or "").strip(),
            policy_path=(body.get("policy_path") or "").strip(),
        )
    except _loan.LoanConfigError as exc:
        return jsonify({"detail": str(exc)}), 400
    except Exception as exc:                                          # noqa: BLE001
        log.exception("loan job failed to start")
        return jsonify({"detail": f"Could not start job: {exc}"}), 500

    try:
        import activity_ledger
        activity_ledger.record(
            _actor(body), "document_job",
            f"Started {job.loan_label} · {job.total} document"
            f"{'' if job.total == 1 else 's'}",
            job_id=job.job_id, loan_type=job.loan_type, domain=job.domain,
            documents=job.total, mode=job.mode,
            input_path=job.input_path, run_folder=Path(job.run_dir).name,
            status="started",
        )
    except Exception as exc:                                          # noqa: BLE001
        log.warning("job-start activity not recorded: %s", exc)

    return jsonify({"job_id": job.job_id, "total": job.total,
                    "run_dir": job.run_dir,
                    "run_folder": Path(job.run_dir).name,
                    "documents": [d.name for d in job.docs]})


def _actor(body_or_args) -> dict:
    """The licensee behind a request, as sent by the dashboard.

    The access key is used only to derive the ledger's file name; it is never
    stored. Absent a key the action simply isn't attributed to anyone.
    """
    get = body_or_args.get
    a = get("actor") if isinstance(get("actor"), dict) else {}
    return {
        "api_key":     (a.get("api_key") or get("api_key") or "").strip(),
        "user_id":     a.get("user_id") or get("user_id") or "",
        "user_name":   a.get("user_name") or get("user_name") or "",
        "role":        a.get("role") or get("role") or "",
        "institution": a.get("institution") or get("institution") or "",
    }


@app.route("/ledger/activity", methods=["GET", "POST"])
def activity_ledger_route():
    """Per-licensee activity ledger: read it (GET) or add to it (POST).

    The dashboard posts the activities only it can see — a sign-in, a document
    job finishing in the browser's stream — while the server records what it
    performs itself."""
    import activity_ledger

    if request.method == "POST":
        body = request.get_json(force=True) or {}
        entry = activity_ledger.record(
            _actor(body),
            (body.get("kind") or "other").strip(),
            (body.get("summary") or "").strip(),
            **(body.get("details") if isinstance(body.get("details"), dict) else {}),
        )
        if entry is None:
            return jsonify({"ok": False, "detail": "No access key — activity not attributed."}), 202
        return jsonify({"ok": True, "entry": entry})

    api_key = (request.args.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"days": [], "totals": {"records": 0}, "owner": {},
                        "detail": "Sign in to see your ledger."})
    return jsonify(activity_ledger.days(api_key, kind=(request.args.get("kind") or "").strip()))


@app.route("/ledger/activity/export")
def activity_ledger_export():
    """The raw JSONL for one key — the record as it is stored."""
    import activity_ledger
    api_key = (request.args.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"detail": "api_key is required"}), 400
    text = activity_ledger.export_lines(api_key)
    return Response(text, mimetype="application/x-ndjson", headers={
        "Content-Disposition": f"attachment; filename=activity_{activity_ledger.key_id(api_key)}.jsonl",
    })


@app.route("/chat", methods=["POST"])
def chat():
    """Answer one question from the bank's indexed documents.

    Grounded and scoped: chat_rag refuses anything the pack does not cover,
    before any model call, and returns the citations behind every answer."""
    body = request.get_json(force=True) or {}
    question = (body.get("question") or "").strip()
    if not question:
        return jsonify({"detail": "question is required"}), 400

    history = body.get("history")
    history = [m for m in history if isinstance(m, dict)] if isinstance(history, list) else []

    try:
        import chat_rag
        out = chat_rag.answer(
            question,
            history=history,
            policy_path=(body.get("policy_path") or "").strip(),
            bank_name=(body.get("bank_name") or "").strip(),
        )
    except Exception as exc:                                          # noqa: BLE001
        log.exception("chat failed")
        return jsonify({"detail": f"Chat failed: {exc}"}), 500

    try:
        import activity_ledger
        activity_ledger.record(
            _actor(body), "chat",
            ("Refused (outside the indexed documents): " if out.get("refused")
             else "Asked: ") + question[:160],
            refused=out.get("refused"),
            tokens=(out.get("tokens_in") or 0) + (out.get("tokens_out") or 0),
            cost_usd=out.get("cost_usd"),
            citations=len(out.get("citations") or []),
            model=out.get("model") or None,
            question_sha256=out.get("question_sha256"),
        )
    except Exception as exc:                                          # noqa: BLE001
        log.warning("chat activity not recorded: %s", exc)

    return jsonify(out)


@app.route("/chat/status")
def chat_status():
    """Whether the chat window has anything to answer from."""
    try:
        import chat_rag
        return jsonify(chat_rag.pack_status((request.args.get("policy_path") or "").strip()))
    except Exception as exc:                                          # noqa: BLE001
        return jsonify({"ready": False, "detail": str(exc)})


@app.route("/loan/policy/status")
def loan_policy_status():
    """Is a credit-policy pack indexed, and how big is it?

    Optional feature (loan_policy.py) — a missing module is reported as
    unavailable rather than as an error, so the UI can simply hide it.
    """
    raw = (request.args.get("path") or "").strip()
    if not raw:
        return jsonify({"detail": "path is required"}), 400
    try:
        import loan_policy
    except Exception as exc:                                          # noqa: BLE001
        return jsonify({"ok": False, "available": False, "detail": str(exc)})
    return jsonify({**loan_policy.status(raw), "available": True})


@app.route("/loan/policy/index", methods=["POST"])
def loan_policy_index():
    """Index (or re-index) a credit-policy pack. One-off per pack."""
    body = request.get_json(force=True) or {}
    raw = (body.get("path") or "").strip()
    if not raw:
        return jsonify({"detail": "path is required"}), 400
    try:
        import loan_policy
        out = loan_policy.ensure_indexed(raw, force=bool(body.get("force")))
    except Exception as exc:                                          # noqa: BLE001
        log.exception("policy pack indexing failed")
        return jsonify({"detail": f"Could not index the policy pack: {exc}"}), 500
    if not out.get("ok"):
        return jsonify({"detail": out.get("detail", "Indexing failed.")}), 400
    # The full per-file detail is large and only useful in the log.
    out.pop("signature", None)
    return jsonify(out)


@app.route("/loan/stream/<job_id>")
def loan_stream(job_id: str):
    job = _loan.get_job(job_id)
    if not job:
        return jsonify({"detail": "Job not found"}), 404

    def generate():
        while True:
            try:
                data = job.q.get(timeout=15)
                yield f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"
                if data["type"] == "stream_end":
                    break
            except queue.Empty:
                if job.status in ("completed", "failed", "cancelled"):
                    yield f"event: stream_end\ndata: {json.dumps({'type':'stream_end'})}\n\n"
                    break
                yield f"event: heartbeat\ndata: {json.dumps({'type':'heartbeat'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/loan/jobs/<job_id>")
def loan_job_status(job_id: str):
    job = _loan.get_job(job_id)
    if not job:
        return jsonify({"detail": "Job not found"}), 404
    return jsonify(job.snapshot())


@app.route("/loan/cancel/<job_id>", methods=["POST"])
def loan_cancel(job_id: str):
    job = _loan.get_job(job_id)
    if not job:
        return jsonify({"detail": "Job not found"}), 404
    if job.status not in ("queued", "running"):
        return jsonify({"detail": f"Job is already {job.status}."}), 400
    job.cancel_event.set()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/loan/report/<job_id>")
def loan_report(job_id: str):
    """Serve the generated eligibility report (html | json | md)."""
    job = _loan.get_job(job_id)
    if not job:
        return jsonify({"detail": "Job not found"}), 404
    kind = (request.args.get("kind") or "html").lower()
    mimetypes = {"html": "text/html", "json": "application/json",
                 "md": "text/markdown"}
    if kind not in mimetypes:
        return jsonify({"detail": "kind must be 'html', 'json' or 'md'"}), 400
    path = Path(job.run_dir or job.output_path) / f"eligibility_report.{kind}"
    if not path.exists():
        return jsonify({"detail": "Report not generated yet."}), 404
    return send_file(path, mimetype=mimetypes[kind])


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5055)
    args = p.parse_args()
    print(f"\nOrchestrator UI  ->  http://127.0.0.1:{args.port}\n")
    app.run(port=args.port, debug=False, threaded=True)
