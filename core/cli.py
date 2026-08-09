# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Command-line entry point."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from decision_ledger import activate_ledger, record as ledger_record, sha256_text

from . import config
from .config import (log, AGENTS_DIR, MCP_CONFIG, PROJECTS_ROOT, MEMORY_ROOT,
                     LLM_PROVIDER, WORKER_MODEL, SUPERVISOR_MODEL, MAX_AGENTS)
from .errors import ApprovalRejectedError, BudgetExhaustedError
from .state import GraphState
from .registry import AgentRegistry
from .agents import AgentFactory
from .projects import ProjectManager
from .runtime import set_run_context, _get_skill_factory, _get_memory_store
from .graph import build_graph, run_with_approvals
from .reporting import write_audit, write_output_summary, print_summary

# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=f"Multi-agent orchestrator — {MAX_AGENTS}-agent budget, per-request projects"
    )
    p.add_argument("--no-venv",       action="store_true", help="Skip venv creation")
    p.add_argument("--codebase",      default="", metavar="PATH",
                   help="Path to an existing codebase to comprehend before planning "
                        "(runs the Stage-0 COMPREHENDER agent and, unless --no-rag, "
                        "indexes it for governed RAG retrieval in every later stage)")
    p.add_argument("--no-rag",        action="store_true",
                   help="Disable the governed RAG pipeline (codebase indexing and "
                        "per-stage retrieval); the Stage-0 digest is still used")
    p.add_argument("--rag-backend",   choices=["auto", "chroma", "jsonl"],
                   default=os.getenv("RAG_BACKEND", "auto"),
                   help="Dense vector search backend for RAG: 'chroma' (ChromaDB "
                        "HNSW ANN), 'jsonl' (stdlib brute-force cosine), or 'auto' "
                        "(chroma if installed, else jsonl). Default: auto")
    p.add_argument("--list-agents",   action="store_true", help="List CLAUDE_*.md definitions")
    p.add_argument("--list-skills",   action="store_true", help="List skills/SKILL_*.md skill cards")
    p.add_argument("--list-memories", action="store_true", help="List memory/ records of past runs")
    p.add_argument("--list-projects", action="store_true", help="List all past project runs")
    return p.parse_args()


def prompt_for_activity() -> str:
    sep = "═" * 70
    print(f"\n{sep}")
    print("  LangChain + LangGraph Multi-Agent Orchestrator  (v3)")
    print(f"  Agent budget: {MAX_AGENTS} max  |  Each run = new isolated project folder")
    print(sep)
    print()
    while True:
        try:
            activity = input("  ▶ What would you like to build? ").strip()
        except EOFError:
            activity = ""
        if len(activity) >= 10:
            return activity
        print("  Please enter at least 10 characters.")


def main() -> None:

    args = parse_args()

    if args.list_agents:
        print(f"\nAgent definitions (in {AGENTS_DIR}):")
        for a in AgentFactory(
            agents_dir=AGENTS_DIR,
            mcp_config=MCP_CONFIG,
            registry=AgentRegistry(PROJECTS_ROOT),  # throwaway
        ).available():
            print(f"  • {a:<18} → {AGENTS_DIR / f'CLAUDE_{a}.md'}")
        print()
        return

    if args.list_skills:
        sf = _get_skill_factory()
        skills = sf.available()
        if not skills:
            print(f"\nNo skill cards found in {sf.skills_dir}\n")
            return
        sep = "─" * 78
        print(f"\n{sep}")
        print(f"  SKILL FACTORY  ({len(skills)} skills in {sf.skills_dir})")
        print(sep)
        for s in skills:
            print(f"  • {s.skill_id:<22} {s.name}")
            print(f"    {'':<22} {s.description}")
            print(f"    {'':<22} stages: {', '.join(s.stages)}")
            print(f"    {'':<22} keywords: {', '.join(s.keywords)}")
            print()
        print(sep + "\n")
        return

    if args.list_memories:
        records = _get_memory_store().all_records()
        if not records:
            print(f"\nNo memory records in {MEMORY_ROOT}\n")
            return
        sep = "─" * 78
        print(f"\n{sep}")
        print(f"  MEMORY STORE  ({len(records)} past runs remembered in {MEMORY_ROOT})")
        print(sep)
        for m in records:
            print(f"  • {m.project_id}")
            print(f"    activity : {m.activity}")
            print(f"    skills   : {', '.join(m.skills) or '—'}"
                  + (f"   | generated: {m.generated_skill}" if m.generated_skill else ""))
            print(f"    files    : {len(m.files)}  | url: {m.server_url or '—'}")
            print()
        print(sep + "\n")
        return

    pm = ProjectManager(PROJECTS_ROOT)

    if args.list_projects:
        projects = pm.list_projects()
        if not projects:
            print("\nNo projects found in", PROJECTS_ROOT)
        else:
            sep = "─" * 70
            print(f"\n{sep}")
            print(f"  {'PROJECT ID':<44} {'STATUS':<12} CREATED")
            print(sep)
            for proj in projects:
                print(
                    f"  {proj['project_id']:<44} "
                    f"{proj.get('status','?'):<12} "
                    f"{proj.get('created_at','?')}"
                )
            print(sep + "\n")
        return

    # ── New run ──────────────────────────────────────────────────────────────
    activity    = prompt_for_activity()
    # Governed RAG configuration (visible in --help; sealed into run_started)
    if args.no_rag:
        config.RAG_ENABLED = False
        os.environ["RAG_DISABLED"] = "1"
    os.environ["RAG_BACKEND"] = args.rag_backend
    log.info("Governed RAG: %s (backend=%s)",
             "enabled" if config.RAG_ENABLED else "DISABLED", args.rag_backend)

    project_dir, thread_id = pm.create(activity)

    # Tamper-evident decision provenance for this run
    activate_ledger(project_dir)
    ledger_record(
        "run_started",
        thread_id=thread_id,
        activity_sha256=sha256_text(activity),
        activity=activity,
        provider=LLM_PROVIDER,
        worker_model=WORKER_MODEL,
        supervisor_model=SUPERVISOR_MODEL,
        existing_codebase=args.codebase or None,
        rag_enabled=config.RAG_ENABLED,
        rag_backend=os.environ.get("RAG_BACKEND", "auto"),
        channel="cli",
    )

    # Initialise singletons scoped to this run
    _registry = AgentRegistry(project_dir)
    _factory  = AgentFactory(
        agents_dir=AGENTS_DIR,
        mcp_config=MCP_CONFIG,
        registry=_registry,
    )
    set_run_context(_registry, _factory)

    checkpointer = MemorySaver()
    app          = build_graph(checkpointer)

    # Each run uses its own thread_id → independent checkpoint namespace
    run_config = {"configurable": {"thread_id": thread_id}}

    initial_state: GraphState = {
        "activity":      activity,
        "project_dir":   str(project_dir),
        "thread_id":     thread_id,
        "skip_venv":     args.no_venv,
        "existing_codebase": args.codebase or "",
        "comprehension": "",
        "plan":          "",
        "spec":          "",
        "env_script":    "",
        "requirements":  "",
        "source_files":  {},
        "test_files":    {},
        "test_report":   "",
        "generated_skill": "",
        "agents_spawned": 0,
        "agent_log":     [],
        "approvals":     [],
        "stage_timings": {},
        "messages":      [],
    }

    log.info("Project  : %s", project_dir)
    log.info("Thread   : %s", thread_id)
    log.info("Budget   : %d agents max", MAX_AGENTS)

    try:
        final_state = run_with_approvals(app, initial_state, run_config)
        pm.complete(project_dir)
        write_audit(final_state, _registry)
        write_output_summary(final_state)
        print_summary(final_state, _registry)

    except BudgetExhaustedError as e:
        log.error("BUDGET EXHAUSTED: %s", e)
        sys.exit(2)

    except ApprovalRejectedError as e:
        log.warning("PIPELINE STOPPED BY USER: %s", e)
        sys.exit(3)
