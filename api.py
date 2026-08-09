"""
api.py
======
FastAPI backend that wraps orchestrator.py and streams live events to the UI
via Server-Sent Events (SSE).

Every state change in the orchestrator — agent spawned, agent alive,
agent torn down, token usage, approval gate, stage complete — is pushed
to connected SSE clients in real time.

Endpoints:
    POST /run              — start a new pipeline run
    GET  /stream/{run_id}  — SSE stream of live events for a run
    POST /approve/{run_id} — send approve/reject decision through interrupt()
    GET  /runs             — list all past project runs
    GET  /venvs            — list all isolated venvs
    GET  /health           — liveness check

Run:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Requirements (add to requirements.txt):
    fastapi>=0.110,<1.0
    uvicorn[standard]>=0.29,<1.0
    sse-starlette>=2.0,<3.0
    anthropic>=0.40,<1.0
    langchain-anthropic>=0.3,<1.0
    langgraph>=0.2,<1.0
    langchain-core>=0.3,<1.0
    python-dotenv>=1.0,<2.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv()


class PipelineCancelledError(Exception):
    """Raised inside the pipeline thread when the user cancels the run."""

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
                    datefmt="%H:%M:%S")

# ── Import orchestrator internals ─────────────────────────────────────────────
# We import the module so we can wrap and patch key classes to emit SSE events.
import orchestrator as orch

app = FastAPI(title="Orchestrator UI API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# In-memory run store
# ─────────────────────────────────────────────────────────────────────────────

class RunState:
    """Tracks one pipeline run end-to-end."""

    def __init__(self, run_id: str, activity: str) -> None:
        self.run_id      = run_id
        self.activity    = activity
        self.status      = "pending"      # pending | running | awaiting_approval | completed | failed
        self.project_dir = ""
        self.venv_dir    = ""
        self.events: list[dict] = []      # full ordered event log
        self._queue: asyncio.Queue = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

        # Token tracking
        self.total_input_tokens  = 0
        self.total_output_tokens = 0

        # Approval gate state
        self._approval_event = threading.Event()
        self._approval_decision: str = "approve"
        self._pending_stage: str = ""

        # Pipeline cancellation
        self._cancel_event:    threading.Event = threading.Event()
        self._cancel_reason:   str = ""

        # Generated app process tracking
        self.app_proc:      subprocess.Popen | None = None
        self.app_url:       str = ""
        self.app_port:      int = 0
        self.app_pid:       int = 0
        self.app_framework: str = ""
        self.app_cmd:       str = ""

    # ── event emission ───────────────────────────────────────────────────────

    def emit(self, event_type: str, data: dict) -> None:
        """Push an event — safe to call from a background thread."""
        payload = {"type": event_type, "ts": datetime.now().isoformat(timespec="milliseconds"), **data}
        self.events.append(payload)
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)

    def emit_log(self, msg: str, level: str = "info") -> None:
        self.emit("log", {"level": level, "msg": msg})

    # ── approval gate ────────────────────────────────────────────────────────

    def wait_for_approval(self, stage: str, content: str = "") -> str:
        """Block the pipeline thread until the UI sends a decision."""
        self._pending_stage = stage
        self.status = "awaiting_approval"
        self.emit("approval_required", {"stage": stage, "content": content})
        self._approval_event.clear()
        self._approval_event.wait(timeout=300)   # 5-minute timeout
        decision = self._approval_decision
        self.status = "running"
        return decision

    def resolve_approval(self, decision: str) -> None:
        self._approval_decision = decision
        self._approval_event.set()

    # ── pipeline cancellation ────────────────────────────────────────────────

    def request_cancel(self, reason: str = "User stopped the pipeline") -> None:
        """Signal the pipeline thread to stop at the next checkpoint."""
        self._cancel_reason = reason
        self._cancel_event.set()
        # If the pipeline is blocked at an approval gate, unblock it so it
        # can notice the cancel flag on its next check.
        self._approval_decision = "reject"
        self._approval_event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()


# Global run store: run_id → RunState
_runs: dict[str, RunState] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Token-tracking wrapper around ChatAnthropic
# ─────────────────────────────────────────────────────────────────────────────

class TrackingChatAnthropic:
    """
    Wraps ChatAnthropic to intercept the response and extract token usage,
    then emit a token_update event to the run's SSE stream.
    """

    def __init__(self, inner, run_state: RunState, agent_id: str) -> None:
        self._inner    = inner
        self._run      = run_state
        self._agent_id = agent_id

    def invoke(self, messages):
        response = self._inner.invoke(messages)

        # Extract usage from AIMessage usage_metadata
        input_tokens  = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            input_tokens  = getattr(um, "input_tokens",  0) or 0
            output_tokens = getattr(um, "output_tokens", 0) or 0
        elif hasattr(response, "response_metadata"):
            rm = response.response_metadata or {}
            usage = rm.get("usage", {})
            input_tokens  = usage.get("input_tokens",  0)
            output_tokens = usage.get("output_tokens", 0)

        self._run.total_input_tokens  += input_tokens
        self._run.total_output_tokens += output_tokens

        self._run.emit("token_update", {
            "agent_id":           self._agent_id,
            "input_tokens":       input_tokens,
            "output_tokens":      output_tokens,
            "total_input_tokens": self._run.total_input_tokens,
            "total_output_tokens":self._run.total_output_tokens,
            "total_tokens":       self._run.total_input_tokens + self._run.total_output_tokens,
        })
        return response

    # Proxy everything else to the inner LLM
    def __getattr__(self, name):
        return getattr(self._inner, name)


# ─────────────────────────────────────────────────────────────────────────────
# Patched AgentRegistry that also emits SSE events
# ─────────────────────────────────────────────────────────────────────────────

class StreamingAgentRegistry(orch.AgentRegistry):
    """Extends AgentRegistry to push every state change to the SSE stream."""

    def __init__(self, project_dir: Path, run_state: RunState) -> None:
        super().__init__(project_dir)
        self._run = run_state

    def register(self, agent_id, slot, model, stage):
        rec = super().register(agent_id, slot, model, stage)
        self._run.emit("agent_registered", {
            "agent_id": agent_id, "slot": slot,
            "model": model, "stage": stage, "status": "PENDING",
        })
        return rec

    def mark_alive(self, agent_id):
        super().mark_alive(agent_id)
        self._run.emit("agent_alive", {
            "agent_id": agent_id, "status": "ALIVE",
            "spawned_at": datetime.now().isoformat(timespec="seconds"),
        })

    def mark_torn_down(self, agent_id, elapsed_s, output_chars):
        super().mark_torn_down(agent_id, elapsed_s, output_chars)
        self._run.emit("agent_torn_down", {
            "agent_id": agent_id, "status": "TORN_DOWN",
            "elapsed_s": elapsed_s, "output_chars": output_chars,
        })

    def mark_failed(self, agent_id, error):
        super().mark_failed(agent_id, error)
        self._run.emit("agent_failed", {"agent_id": agent_id, "error": error})

    # Suppress terminal table printing in UI mode
    def _print_table(self, event: str) -> None:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Patched AgentFactory that wraps LLM with token tracker
# ─────────────────────────────────────────────────────────────────────────────

class StreamingAgentFactory(orch.AgentFactory):

    def __init__(self, agents_dir, mcp_config, registry, run_state: RunState) -> None:
        super().__init__(agents_dir, mcp_config, registry)
        self._run = run_state

    def spawn(self, agent_id, stage, supervisor=False, inject_mcp=False):
        # Call parent spawn to get the _EphemeralAgent
        agent = super().spawn(agent_id, stage, supervisor, inject_mcp)

        # Wrap the inner LLM with our token tracker
        inner_llm  = agent._llm
        tracking   = TrackingChatAnthropic(inner_llm, self._run, agent_id)
        agent._llm = tracking

        # Rebuild the LangChain chain with the tracking wrapper
        from langchain_core.prompts import ChatPromptTemplate
        agent._prompt = ChatPromptTemplate.from_messages([
            ("system", "{system}"),
            ("human",  "{user}"),
        ])
        agent._chain = agent._prompt | tracking

        self._run.emit_log(f"Agent spawned: {agent_id} (slot {self._total_spawned}/{orch.MAX_AGENTS})")
        return agent

    def display_agent_file(self, agent_id):
        """Emit agent file content to SSE instead of printing."""
        md_path = self.agents_dir / f"CLAUDE_{agent_id}.md"
        content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        self._run.emit("agent_file_preview", {
            "agent_id":    agent_id,
            "filename":    f"CLAUDE_{agent_id}.md",
            "content":     content,
            "budget_used": self._total_spawned,
            "budget_max":  orch.MAX_AGENTS,
        })
        return content


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline runner (runs in a background thread)
# ─────────────────────────────────────────────────────────────────────────────

def _run_pipeline(run: RunState) -> None:
    """
    Full pipeline execution in a background thread.
    Patches module-level singletons so all agents emit to this run's SSE stream.
    Uses the interrupt() hook to route approval gates through the UI instead
    of terminal input().
    """
    try:
        run.status = "running"
        run.emit("pipeline_started", {"activity": run.activity})

        # ── 1. Create project + venv dirs ────────────────────────────────────
        pm          = orch.ProjectManager(orch.PROJECTS_ROOT)
        project_dir, thread_id = pm.create(run.activity)
        run.project_dir = str(project_dir)
        run.emit("project_created", {"project_dir": str(project_dir), "thread_id": thread_id})

        # ── 2. Initialise streaming registry + factory ────────────────────────
        registry = StreamingAgentRegistry(project_dir, run)
        vm       = orch.VenvManager(orch.VENVS_ROOT)
        factory  = StreamingAgentFactory(
            agents_dir=orch.AGENTS_DIR,
            mcp_config=orch.MCP_CONFIG,
            registry=registry,
            run_state=run,
        )

        # Patch module globals so LangGraph nodes pick up our streaming versions
        orch._registry     = registry
        orch._factory      = factory
        orch._venv_manager = vm

        # ── 3. Replace interrupt() with our approval gate ─────────────────────
        # We monkey-patch langgraph.types.interrupt inside this thread so that
        # every interrupt() call goes through run.wait_for_approval() instead
        # of suspending the graph.
        import langgraph.types as _lgt

        _original_interrupt = _lgt.interrupt

        def _ui_interrupt(value):
            stage   = value.get("stage", "unknown") if isinstance(value, dict) else str(value)
            content = value.get("content", "")       if isinstance(value, dict) else ""
            decision = run.wait_for_approval(stage, content)
            if decision == "reject":
                raise orch.ApprovalRejectedError(f"User rejected stage '{stage}'.")
            return decision

        _lgt.interrupt = _ui_interrupt
        # Also patch the imported name in orchestrator module
        orch.interrupt = _ui_interrupt

        # ── 4. Build graph and run ────────────────────────────────────────────
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        app_graph    = orch.build_graph(checkpointer)
        config       = {"configurable": {"thread_id": thread_id}}

        initial_state = {
            "activity":      run.activity,
            "project_dir":   str(project_dir),
            "venv_dir":      "",
            "thread_id":     thread_id,
            "skip_venv":     False,
            "plan":          "",
            "spec":          "",
            "env_script":    "",
            "requirements":  "",
            "source_files":  {},
            "agents_spawned": 0,
            "agent_log":     [],
            "approvals":     [],
            "stage_timings": {},
            "messages":      [],
            "app_url":       "",
            "app_port":      0,
            "app_pid":       0,
            "app_cmd":       "",
            "app_framework": "",
        }

        # Emit stage transitions by wrapping node functions
        _wrap_nodes_for_stage_events(run)

        final_state = app_graph.invoke(initial_state, config=config)

        # ── 5. Finalise ───────────────────────────────────────────────────────
        pm.complete(project_dir)
        orch.write_audit(final_state, registry)

        run.venv_dir    = final_state.get("venv_dir", "")
        run.app_url     = final_state.get("app_url", "")
        run.app_port    = final_state.get("app_port", 0)
        run.app_pid     = final_state.get("app_pid", 0)
        run.app_framework = final_state.get("app_framework", "")
        run.app_cmd     = final_state.get("app_cmd", "")
        run.status      = "completed"
        run.emit("pipeline_completed", {
            "project_dir":         run.project_dir,
            "venv_dir":            run.venv_dir,
            "total_input_tokens":  run.total_input_tokens,
            "total_output_tokens": run.total_output_tokens,
            "total_tokens":        run.total_input_tokens + run.total_output_tokens,
            "files":               list(final_state.get("source_files", {}).keys()),
        })
        if run.app_url:
            run.emit("app_launched", {
                "url":       run.app_url,
                "port":      run.app_port,
                "pid":       run.app_pid,
                "framework": run.app_framework,
                "cmd":       run.app_cmd,
            })

    except PipelineCancelledError as e:
        run.status = "cancelled"
        run.emit("pipeline_cancelled", {"reason": str(e)})
    except orch.ApprovalRejectedError as e:
        run.status = "rejected"
        run.emit("pipeline_rejected", {"reason": str(e)})
    except orch.BudgetExhaustedError as e:
        run.status = "failed"
        run.emit("pipeline_failed", {"reason": str(e)})
    except Exception as e:
        # Also surface cancellation that bubbled up as a generic exception
        if run.is_cancelled:
            run.status = "cancelled"
            run.emit("pipeline_cancelled", {"reason": run._cancel_reason or str(e)})
        else:
            run.status = "failed"
            run.emit("pipeline_failed", {
                "reason": str(e),
                "traceback": traceback.format_exc(),
            })
    finally:
        # Restore original interrupt
        try:
            import langgraph.types as _lgt
            _lgt.interrupt = _original_interrupt
        except Exception:
            pass
        run.emit("stream_end", {})


def _wrap_nodes_for_stage_events(run: RunState) -> None:
    """
    Wrap each LangGraph node function to emit stage_started / stage_completed
    events around the actual node logic.
    """
    stage_map = {
        "planner_node":      "plan",
        "spec_writer_node":  "spec",
        "env_builder_node":  "env",
        "executor_node":     "execute",
        "launch_app_node":   "launch",
    }
    for fn_name, stage in stage_map.items():
        original = getattr(orch, fn_name)

        def make_wrapper(orig, s):
            def wrapper(state):
                # Check for cancel before starting each stage
                if run.is_cancelled:
                    raise PipelineCancelledError(run._cancel_reason)
                run.emit("stage_started", {"stage": s})
                result = orig(state)
                run.emit("stage_completed", {"stage": s})
                return result
            wrapper.__name__ = orig.__name__
            return wrapper

        setattr(orch, fn_name, make_wrapper(original, stage))


# ─────────────────────────────────────────────────────────────────────────────
# API endpoints
# ─────────────────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    activity: str


class ApprovalRequest(BaseModel):
    decision: str   # "approve" or "reject"


@app.post("/run")
async def start_run(req: RunRequest):
    """Start a new pipeline run. Returns run_id immediately."""
    if len(req.activity.strip()) < 10:
        raise HTTPException(400, "Activity must be at least 10 characters.")

    run_id = str(uuid.uuid4())[:8]
    run    = RunState(run_id=run_id, activity=req.activity.strip())
    run._loop = asyncio.get_running_loop()
    _runs[run_id] = run

    # Launch pipeline in background thread
    t = threading.Thread(target=_run_pipeline, args=(run,), daemon=True)
    t.start()

    return {"run_id": run_id, "status": "started"}


@app.get("/stream/{run_id}")
async def stream_events(run_id: str):
    """SSE stream — push live events to the UI for a given run."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found.")

    # Make sure the loop reference is set
    run._loop = asyncio.get_running_loop()

    async def generator() -> AsyncIterator[dict]:
        # Replay any events that already arrived before the client connected
        for evt in list(run.events):
            yield {"event": evt["type"], "data": json.dumps(evt)}

        # Stream new events
        while True:
            if run.status in ("completed", "failed", "rejected", "cancelled"):
                try:
                    evt = run._queue.get_nowait()
                    yield {"event": evt["type"], "data": json.dumps(evt)}
                except asyncio.QueueEmpty:
                    break
            else:
                try:
                    evt = await asyncio.wait_for(run._queue.get(), timeout=30)
                    yield {"event": evt["type"], "data": json.dumps(evt)}
                    if evt["type"] == "stream_end":
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": json.dumps({"ts": datetime.now().isoformat()})}

    return EventSourceResponse(generator())


@app.post("/approve/{run_id}")
async def approve(run_id: str, req: ApprovalRequest):
    """Send approve/reject decision for a pending approval gate."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found.")
    if run.status != "awaiting_approval":
        raise HTTPException(400, f"Run '{run_id}' is not awaiting approval (status={run.status}).")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(400, "Decision must be 'approve' or 'reject'.")

    run.resolve_approval(req.decision)
    return {"run_id": run_id, "decision": req.decision}


@app.get("/runs")
async def list_runs():
    """List all past project runs from disk."""
    try:
        pm = orch.ProjectManager(orch.PROJECTS_ROOT)
        return {"runs": pm.list_projects()}
    except Exception as e:
        return {"runs": [], "error": str(e)}


@app.get("/venvs")
async def list_venvs():
    """List all isolated venvs and their disk sizes."""
    try:
        vm = orch.VenvManager(orch.VENVS_ROOT)
        return {"venvs": vm.list_venvs()}
    except Exception as e:
        return {"venvs": [], "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok", "active_runs": len([r for r in _runs.values() if r.status == "running"])}


@app.post("/cancel/{run_id}")
async def cancel_pipeline(run_id: str):
    """Stop the pipeline at the next stage boundary. Safe to call at any time."""
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found.")
    if run.status in ("completed", "failed", "rejected", "cancelled"):
        raise HTTPException(400, f"Run '{run_id}' is already finished (status={run.status}).")
    run.request_cancel("User stopped the pipeline")
    log.info("Pipeline cancel requested for run %s", run_id)
    return {"run_id": run_id, "cancelled": True, "status": run.status}


@app.post("/stop/{run_id}")
async def stop_app(run_id: str):
    """Kill the generated app subprocess for a completed run."""
    import signal, platform
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found.")
    if not run.app_pid:
        raise HTTPException(400, "No running app process for this run.")
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(run.app_pid), "/F"], check=False)
        else:
            import os as _os
            _os.kill(run.app_pid, signal.SIGTERM)
        old_pid   = run.app_pid
        old_url   = run.app_url
        run.app_pid = 0
        run.app_url = ""
        run.emit("app_stopped", {"pid": old_pid, "url": old_url})
        return {"stopped": True, "pid": old_pid}
    except Exception as e:
        raise HTTPException(500, f"Failed to stop process: {e}")


@app.get("/app-status/{run_id}")
async def app_status(run_id: str):
    """Return current status of the generated app process."""
    import psutil
    run = _runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found.")
    pid_alive = False
    if run.app_pid:
        try:
            pid_alive = psutil.pid_exists(run.app_pid)
        except Exception:
            # psutil may not be installed — fall back to os.kill check
            import os as _os, sys as _sys
            try:
                if _sys.platform == "win32":
                    import ctypes
                    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, run.app_pid)
                    pid_alive = h != 0
                    if h: ctypes.windll.kernel32.CloseHandle(h)
                else:
                    _os.kill(run.app_pid, 0)
                    pid_alive = True
            except (ProcessLookupError, PermissionError):
                pid_alive = False
    return {
        "run_id":    run_id,
        "app_url":  run.app_url,
        "app_port": run.app_port,
        "app_pid":  run.app_pid,
        "app_cmd":  run.app_cmd,
        "framework": run.app_framework,
        "running":  pid_alive,
    }


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the dashboard UI."""
    ui_path = Path(__file__).parent / "ui.html"
    if ui_path.exists():
        return HTMLResponse(ui_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>ui.html not found — place it in the same directory as api.py</h1>")