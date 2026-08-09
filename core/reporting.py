# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Run outputs: summary file, audit_log.json, terminal summary."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from decision_ledger import active_ledger, record as ledger_record, sha256_text

from .config import log, WORKER_MODEL, SUPERVISOR_MODEL, LLM_PROVIDER, MAX_AGENTS
from .state import GraphState
from .registry import AgentRegistry
from .projects import detect_server_url
from .runtime import _get_memory_store

# ─────────────────────────────────────────────────────────────────────────────

def write_output_summary(state: GraphState) -> None:
    """Write generated_output.txt with project info, file list, and server URL."""
    project_dir = Path(state["project_dir"])
    server_url  = detect_server_url(project_dir)
    port        = server_url.split(":")[-1] if server_url else "N/A"

    lines = [
        "ORCHESTRATOR - GENERATED OUTPUT SUMMARY",
        "=" * 60,
        f"Activity    : {state['activity']}",
        f"Project Dir : {project_dir.resolve()}",
        f"Thread ID   : {state['thread_id']}",
        f"Generated   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    if server_url:
        lines += [
            "SERVER",
            "-" * 60,
            f"URL         : {server_url}",
            f"Port        : {port}",
            f"Start cmd   : cd \"{project_dir.resolve()}\" && python app.py",
            "",
        ]

    lines += [
        "GENERATED FILES",
        "-" * 60,
    ]
    for p in sorted(project_dir.rglob("*")):
        if p.is_file() and ".venv" not in p.parts and p.suffix not in (".json",):
            lines.append(f"  {p.relative_to(project_dir)}")

    lines += [
        "",
        "=" * 60,
    ]

    (project_dir / "generated_output.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def write_audit(state: GraphState, registry: AgentRegistry) -> None:
    project_dir = Path(state["project_dir"])
    audit = {
        "project_id":     state["thread_id"],
        "activity":       state["activity"],
        "agents_spawned": state.get("agents_spawned", 0),
        "budget_limit":   MAX_AGENTS,
        "agent_log":      state.get("agent_log", []),
        "registry":       [r.as_dict() for r in registry.all_records()],
        "approvals":      state.get("approvals", []),
        "stage_timings":  state.get("stage_timings", {}),
        "files_generated": list(state.get("source_files", {}).keys()),
        "test_files":      list(state.get("test_files", {}).keys()),
        "generated_skill": state.get("generated_skill", ""),
    }

    # Seal the decision ledger: one closing entry, then embed the chain head
    # in audit_log.json so the summary and the ledger cross-attest each other.
    ledger_record(
        "run_complete",
        thread_id=state["thread_id"],
        stages_approved=state.get("approvals", []),
        files_generated_sha256={
            name: sha256_text(src)
            for name, src in state.get("source_files", {}).items()
        },
        comprehension_used=bool(state.get("comprehension")),
    )
    ledger = active_ledger()
    if ledger is not None:
        ok, entries, err = ledger.verify()
        audit["decision_ledger"] = {
            "file":          ledger.path.name,
            "entries":       entries,
            "head_hash":     ledger.head_hash,
            "chain_valid":   ok,
            "chain_error":   err,
        }
        if not ok:
            log.error("Decision ledger FAILED verification: %s", err)

    (project_dir / "audit_log.json").write_text(
        json.dumps(audit, indent=2), encoding="utf-8"
    )

    # Long-term memory: distil this run into memory/<project_id>.json so future
    # runs can recall it. write_audit is called by both the CLI and the web
    # backend on completion, so recording here covers both. Best-effort.
    try:
        _get_memory_store().record_run(state)
    except Exception as exc:
        log.warning("Memory record failed (audit unaffected): %s", exc)


def print_summary(state: GraphState, registry: AgentRegistry) -> None:
    sep = "=" * 70
    project_dir = Path(state["project_dir"])
    server_url  = detect_server_url(project_dir)

    print(f"\n{sep}")
    print("  ORCHESTRATION COMPLETE")
    print(sep)
    print(f"  Activity   : {state['activity']}")
    print(f"  Project    : {project_dir.resolve()}")
    print(f"  Thread ID  : {state['thread_id']}")
    print(f"  Agents     : {state.get('agents_spawned', 0)} / {MAX_AGENTS} used")
    if state.get("generated_skill"):
        print(f"  New skill  : {state['generated_skill']} — added to skill factory for future runs")
    if server_url:
        print(f"  Server     : {server_url}")
        print(f"  Run cmd    : cd \"{project_dir.resolve()}\" && python app.py")
    print()
    print("  Agent registry at completion:")
    print(f"  {'#':<4} {'ID':<18} {'STAGE':<12} {'STATUS':<12} {'ELAPSED':>8}")
    print(f"  {'-'*4} {'-'*18} {'-'*12} {'-'*12} {'-'*8}")
    for r in registry.all_records():
        icon = {"ALIVE":"[OK]","TORN_DOWN":"[--]","PENDING":"[..]","FAILED":"[!!]"}.get(r.status.value,"")
        print(f"  {r.slot:<4} {r.agent_id:<18} {r.stage:<12} {icon} {r.status.value:<10} {r.elapsed_s:>6.1f}s")
    print()
    print("  Files:")
    for p in sorted(project_dir.rglob("*")):
        if p.is_file() and ".venv" not in p.parts:
            print(f"    {p.relative_to(project_dir)}")
    if server_url:
        print()
        print(f"  ** Open {server_url} after starting the project **")
    print(sep + "\n")


