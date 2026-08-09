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
        self.q: queue.Queue  = queue.Queue()
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
        self.q.put(data)

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
    _runs[run_id] = ctx

    t = threading.Thread(target=_run_pipeline, args=(ctx, True), daemon=True)
    t.start()

    return jsonify({"run_id": run_id})


@app.route("/stream/<run_id>")
def stream(run_id: str):
    ctx = _runs.get(run_id)
    if not ctx:
        return jsonify({"detail": "Run not found"}), 404

    def generate():
        # Heartbeat while pipeline hasn't sent stream_end
        while True:
            try:
                data = ctx.q.get(timeout=15)
                yield f"event: {data['type']}\ndata: {json.dumps(data)}\n\n"
                if data["type"] == "stream_end":
                    break
            except queue.Empty:
                if ctx.status in ("completed", "failed", "cancelled"):
                    # Run is over and its queue is drained — tell late or
                    # reconnecting clients to stop instead of holding a
                    # zombie connection on heartbeats forever.
                    yield f"event: stream_end\ndata: {json.dumps({'type': 'stream_end'})}\n\n"
                    break
                yield f"event: heartbeat\ndata: {json.dumps({'type':'heartbeat'})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=5055)
    args = p.parse_args()
    print(f"\nOrchestrator UI  ->  http://127.0.0.1:{args.port}\n")
    app.run(port=args.port, debug=False, threaded=True)
