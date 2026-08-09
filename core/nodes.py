# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Pipeline stage nodes, HITL approval gates, and per-stage context helpers."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from comprehension import build_codebase_digest
from decision_ledger import record as ledger_record, sha256_text
from rag_pipeline import get_store as rag_get_store, RagStore

from . import config
from .config import (log, WORKER_MODEL, SUPERVISOR_MODEL, MAX_AGENTS,
                     LLM_PROVIDER)
from .errors import ApprovalRejectedError, BudgetExhaustedError
from .state import GraphState
from .skills import Skill
from .memory import MemoryRecord, MemoryStore
from .parsing import (parse_env_blocks, parse_file_blocks, parse_test_output,
                      syntax_check, parse_skill_card)
from .docx_export import export_docx
from .runtime import (create_venv, _get_registry, _get_factory,
                      _get_skill_factory, _get_memory_store)

def _memories_for(state: GraphState) -> list[MemoryRecord]:
    """Recall past runs relevant to this activity and persist what was recalled
    to projects/<id>/memory_recall.json (logged once per run)."""
    memories = _get_memory_store().recall(
        state["activity"], exclude_project=state.get("thread_id")
    )
    recall_path = Path(state["project_dir"]) / "memory_recall.json"
    if not recall_path.exists():
        if memories:
            log.info(
                "MemoryStore ▶ recalled %d past run(s): %s",
                len(memories), ", ".join(m.project_id for m in memories),
            )
        recall_path.write_text(
            json.dumps([m.project_id for m in memories], indent=2), encoding="utf-8"
        )
    return memories


def _rag_codebase_context(state: "GraphState", query: str,
                          agent_id: str, k: int = 5) -> str:
    """Governed retrieval over the client's existing codebase.

    Only active when the run points at an existing codebase (the
    govern/enhance flow). Returns a prompt section of the most relevant
    chunks with source/span provenance; each retrieval is sealed into the
    decision ledger (query hash + chunk hashes + scores) so the run record
    proves exactly what code context each agent saw. Best-effort: any
    failure returns "" and the pipeline proceeds without RAG context.
    """
    if not config.RAG_ENABLED or not (state.get("existing_codebase") or "").strip():
        return ""
    try:
        store = rag_get_store(state["project_dir"],
                              f"codebase:{state['thread_id']}")
        hits = store.retrieve(query, k=k, agent_id=agent_id)
        if not hits:
            return ""
        log.info("RAG ▶ [%s] retrieved %d chunk(s): %s", agent_id, len(hits),
                 ", ".join(f"{h.chunk.source}[{h.chunk.span}]" for h in hits))
        return "\n\n" + RagStore.render_context(
            hits, header="Relevant excerpts from the EXISTING codebase "
                         "(retrieved, ledger-sealed)")
    except Exception as exc:                                  # noqa: BLE001
        log.warning("RAG ▶ context skipped for [%s]: %s", agent_id, exc)
        return ""


def _skills_for(state: GraphState, stage: str) -> list[Skill]:
    """Match skill cards to the user's activity for this stage, persist the
    assignment to projects/<id>/skills_assigned.json, and return them."""
    skills = _get_skill_factory().match(state["activity"], stage=stage)
    if skills:
        log.info(
            "SkillFactory ▶ stage '%s' assigned: %s",
            stage, ", ".join(s.skill_id for s in skills),
        )
    path = Path(state["project_dir"]) / "skills_assigned.json"
    assignments = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assignments[stage] = [s.as_dict() for s in skills]
    path.write_text(json.dumps(assignments, indent=2), encoding="utf-8")
    return skills


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Node helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_budget() -> None:
    if _get_factory().budget_remaining < 1:
        raise BudgetExhaustedError(
            f"Cannot spawn more agents: budget of {MAX_AGENTS} exhausted."
        )


def _approval_gate(
    stage:       str,
    prompt_text: str,
    content:     str  = "",
    editable:    bool = False,
) -> str | None:
    """Suspend via LangGraph interrupt() and raise on reject.

    For editable gates (plan/spec documents) the full content is included in
    the interrupt payload so the UI can display it as a document; the resume
    value may then be a dict {"decision": "approve", "content": <edited text>}
    instead of a plain "approve"/"reject" string. Returns the edited content
    if the user changed the document, else None."""
    payload: dict[str, Any] = {"stage": stage, "prompt": prompt_text}
    if content:
        payload["content"] = content
    if editable:
        payload["editable"] = True

    ledger_record(
        "gate_presented",
        gate=stage,
        editable=editable,
        artifact_sha256=sha256_text(content) if content else None,
        artifact_chars=len(content) if content else 0,
    )
    decision = interrupt(payload)

    edited: str | None = None
    approver = None
    if isinstance(decision, dict):
        edited   = decision.get("content")
        approver = decision.get("approver")   # web UI may attach an identity
        decision = decision.get("decision", "approve")

    verdict = str(decision).strip().lower()
    was_edited = bool(edited is not None and edited.strip()
                      and edited.strip() != content.strip())
    ledger_record(
        "gate_decision",
        gate=stage,
        decision="reject" if verdict == "reject" else "approve",
        approver=approver,
        edited=was_edited,
        approved_artifact_sha256=(
            sha256_text(edited.strip()) if was_edited
            else (sha256_text(content) if content else None)
        ),
    )
    if verdict == "reject":
        raise ApprovalRejectedError(f"User rejected stage '{stage}'.")
    return edited


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Nodes
# ─────────────────────────────────────────────────────────────────────────────

def comprehender_node(state: GraphState) -> dict[str, Any]:
    """Stage 0 — Legacy Comprehension (optional).

    When the run points at an existing codebase, digest it and have the
    COMPREHENDER agent produce architecture.md, business_rules.md and
    risk_register.md *before* the Planner proposes any change. When no
    codebase is given, this node is a zero-cost passthrough (no agent
    spawned, no approval gate)."""
    codebase = (state.get("existing_codebase") or "").strip()
    if not codebase:
        return {}

    log.info("━" * 60); log.info("NODE  comprehender_node  [Stage 0 — Legacy Comprehension]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    digest, stats = build_codebase_digest(codebase)
    log.info("Comprehension digest: %d/%d files included (%d chars)%s",
             stats.files_included, stats.files_seen, len(digest),
             "  [truncated to budget]" if stats.truncated else "")
    ledger_record(
        "codebase_digested",
        codebase_path=codebase,
        files_seen=stats.files_seen,
        files_included=stats.files_included,
        digest_sha256=sha256_text(digest),
        secrets_withheld=stats.files_skipped_secret,
    )

    # Index the full codebase for governed retrieval. The digest above is
    # size-capped (overview); the RAG index has no such ceiling — every
    # later stage can retrieve the exact modules it is about to touch.
    rag_context = ""
    try:
        if not config.RAG_ENABLED:
            raise RuntimeError("RAG disabled (--no-rag / RAG_DISABLED)")
        store = rag_get_store(state["project_dir"],
                              f"codebase:{state['thread_id']}")
        ingest = store.ingest_path(codebase)
        log.info("RAG ▶ indexed codebase: %d chunk(s) from %d file(s) "
                 "[backend=%s]", ingest["chunks_added"], ingest["files_seen"],
                 store.stats()["dense_backend"])
        ledger_record(
            "codebase_indexed",
            codebase_path=codebase,
            files_seen=ingest["files_seen"],
            chunks_added=ingest["chunks_added"],
            total_chunks=ingest["total_chunks"],
            secrets_withheld=ingest["skipped_secret"],
            dense_backend=store.stats()["dense_backend"],
        )
        hits = store.retrieve(state["activity"], k=8, agent_id="COMPREHENDER")
        if hits:
            rag_context = "\n\n" + RagStore.render_context(
                hits, header="Most relevant code for this activity (retrieved)")
    except Exception as exc:                                  # noqa: BLE001
        log.warning("RAG ▶ codebase indexing skipped: %s", exc)

    factory.display_agent_file("COMPREHENDER")
    _approval_gate("comprehender:agent_file",
                   "Approve CLAUDE_COMPREHENDER.md? [approve/reject]: ")

    skills = _skills_for(state, "plan")   # fintech/insurance cards apply here too
    agent  = factory.spawn("COMPREHENDER", stage="comprehend", skills=skills)
    analysis = agent.invoke(
        f"Activity the team ultimately wants:\n\n{state['activity']}\n\n"
        f"Existing codebase to comprehend first:\n\n{digest}{rag_context}"
    )

    project_dir = Path(state["project_dir"])

    def _section(marker: str) -> str:
        m = re.search(rf"==={marker}===\s*\n(.*?)(?=\n===[A-Z_]+===|\Z)",
                      analysis, re.DOTALL)
        return m.group(1).strip() if m else ""

    sections = {
        "architecture.md":   _section("ARCHITECTURE"),
        "business_rules.md": _section("BUSINESS_RULES"),
        "risk_register.md":  _section("RISK_REGISTER"),
    }
    if not any(sections.values()):
        # Agent ignored the markers — keep everything rather than lose it.
        sections = {"architecture.md": analysis}
    for fname, body in sections.items():
        if body:
            (project_dir / fname).write_text(body, encoding="utf-8")

    _approval_gate(
        "comprehender:output",
        "Approve the comprehension analysis (architecture / rules / risks)? [approve/reject]: ",
        content=analysis, editable=True,
    )

    elapsed = time.perf_counter() - t0
    return {
        "comprehension":  analysis,
        "agents_spawned": factory.total_spawned,
        "agent_log":      state.get("agent_log", []) + [
            {"id": "COMPREHENDER", "model": WORKER_MODEL, "stage": "comprehend",
             "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":      state.get("approvals", []) + ["comprehender:approved"],
        "stage_timings":  {**state.get("stage_timings", {}), "comprehend": round(elapsed, 2)},
        "messages":       [HumanMessage(content=f"[ComprehenderAgent] {len(analysis)} chars — approved")],
    }


def planner_node(state: GraphState) -> dict[str, Any]:
    log.info("━" * 60); log.info("NODE  planner_node  [Stage 1 — Planning]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    factory.display_agent_file("PLANNER")
    _approval_gate("planner:agent_file", "Approve CLAUDE_PLANNER.md? [approve/reject]: ")

    skills = _skills_for(state, "plan")
    agent  = factory.spawn("PLANNER", stage="plan", skills=skills,
                           memories=_memories_for(state))
    planner_msg = f"Activity to plan:\n\n{state['activity']}"
    if state.get("comprehension"):
        planner_msg += (
            "\n\n---\n\nAn approved comprehension analysis of the EXISTING "
            "system is provided below. Your plan must build on this reality — "
            "respect the documented business rules and address the risk "
            "register; do not plan a greenfield rewrite unless the activity "
            "explicitly asks for one.\n\n" + state["comprehension"]
        )
    planner_msg += _rag_codebase_context(state, state["activity"], "PLANNER")
    plan   = agent.invoke(planner_msg)

    project_dir = Path(state["project_dir"])
    plan_path   = project_dir / "plan.md"
    plan_path.write_text(
        f"# Plan: {state['activity']}\n\n{plan}", encoding="utf-8"
    )

    edited = _approval_gate(
        "planner:output", "Approve the plan? [approve/reject]: ",
        content=plan, editable=True,
    )
    if edited is not None and edited.strip() and edited.strip() != plan.strip():
        # Web UI: user edited the plan document before approving
        plan = edited.strip()
        plan_path.write_text(f"# Plan: {state['activity']}\n\n{plan}", encoding="utf-8")
        log.info("Plan replaced by user edits (%d chars)", len(plan))
    else:
        # CLI: user may have edited plan.md on disk while the run was paused
        body = re.sub(r"^# Plan:[^\n]*\n+", "", plan_path.read_text(encoding="utf-8"), count=1)
        if body.strip() and body.strip() != plan.strip():
            plan = body.strip()
            log.info("Plan updated from edited plan.md on disk (%d chars)", len(plan))

    try:
        export_docx(f"Project Plan — {state['activity']}", plan, project_dir / "plan.docx")
    except Exception as exc:
        log.warning("plan.docx export failed: %s", exc)

    elapsed = time.perf_counter() - t0
    return {
        "plan":          plan,
        "agents_spawned": factory.total_spawned,
        "agent_log":     state.get("agent_log", []) + [
            {"id": "PLANNER", "model": WORKER_MODEL, "stage": "plan", "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":     state.get("approvals", []) + ["planner:approved"],
        "stage_timings": {**state.get("stage_timings", {}), "plan": round(elapsed, 2)},
        "messages":      [HumanMessage(content=f"[PlannerAgent] {len(plan)} chars — approved")],
    }


def spec_writer_node(state: GraphState) -> dict[str, Any]:
    log.info("━" * 60); log.info("NODE  spec_writer_node  [Stage 2 — Specification]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    factory.display_agent_file("SPEC_WRITER")
    _approval_gate("spec_writer:agent_file", "Approve CLAUDE_SPEC_WRITER.md? [approve/reject]: ")

    skills = _skills_for(state, "spec")
    agent  = factory.spawn("SPEC_WRITER", stage="spec", skills=skills,
                           memories=_memories_for(state))
    spec   = agent.invoke(
        f"Activity:\n{state['activity']}\n\nProject Plan:\n{state['plan']}"
        + _rag_codebase_context(
            state, f"{state['activity']}\n{state['plan'][:600]}", "SPEC_WRITER")
    )

    spec_path = Path(state["project_dir"]) / "spec.md"
    spec_path.write_text(
        f"# Spec: {state['activity']}\n\n{spec}", encoding="utf-8"
    )

    edited = _approval_gate(
        "spec_writer:output", "Approve the spec? [approve/reject]: ",
        content=spec, editable=True,
    )
    if edited is not None and edited.strip() and edited.strip() != spec.strip():
        spec = edited.strip()
        spec_path.write_text(f"# Spec: {state['activity']}\n\n{spec}", encoding="utf-8")
        log.info("Spec replaced by user edits (%d chars)", len(spec))
    else:
        body = re.sub(r"^# Spec:[^\n]*\n+", "", spec_path.read_text(encoding="utf-8"), count=1)
        if body.strip() and body.strip() != spec.strip():
            spec = body.strip()
            log.info("Spec updated from edited spec.md on disk (%d chars)", len(spec))

    try:
        export_docx(f"Technical Specification — {state['activity']}", spec,
                    spec_path.with_name("spec.docx"))
    except Exception as exc:
        log.warning("spec.docx export failed: %s", exc)

    elapsed = time.perf_counter() - t0
    return {
        "spec":          spec,
        "agents_spawned": factory.total_spawned,
        "agent_log":     state.get("agent_log", []) + [
            {"id": "SPEC_WRITER", "model": WORKER_MODEL, "stage": "spec", "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":     state.get("approvals", []) + ["spec_writer:approved"],
        "stage_timings": {**state.get("stage_timings", {}), "spec": round(elapsed, 2)},
        "messages":      [HumanMessage(content=f"[SpecWriterAgent] {len(spec)} chars — approved")],
    }


def env_builder_node(state: GraphState) -> dict[str, Any]:
    log.info("━" * 60); log.info("NODE  env_builder_node  [Stage 3 — Environment]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    factory.display_agent_file("ENV_BUILDER")
    _approval_gate("env_builder:agent_file", "Approve CLAUDE_ENV_BUILDER.md? [approve/reject]: ")

    skills = _skills_for(state, "env")
    agent  = factory.spawn("ENV_BUILDER", stage="env", skills=skills,
                           memories=_memories_for(state))
    raw    = agent.invoke(
        f"Activity:\n{state['activity']}\n\n"
        f"Plan:\n{state['plan']}\n\nSpec:\n{state['spec']}"
    )

    env_script, requirements = parse_env_blocks(raw)
    project_dir = Path(state["project_dir"])
    req_path    = project_dir / "requirements.txt"
    req_path.write_text(requirements, encoding="utf-8")
    (project_dir / "setup_env.sh").write_text(env_script, encoding="utf-8")

    combined = f"### requirements.txt\n\n{requirements}\n\n### setup_env.sh\n\n{env_script}"
    _approval_gate("env_builder:output", "Approve requirements.txt + setup_env.sh? [approve/reject]: ")

    if not state.get("skip_venv"):
        create_venv(project_dir / ".venv", req_path)

    elapsed = time.perf_counter() - t0
    return {
        "env_script":    env_script,
        "requirements":  requirements,
        "agents_spawned": factory.total_spawned,
        "agent_log":     state.get("agent_log", []) + [
            {"id": "ENV_BUILDER", "model": WORKER_MODEL, "stage": "env", "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":     state.get("approvals", []) + ["env_builder:approved"],
        "stage_timings": {**state.get("stage_timings", {}), "env": round(elapsed, 2)},
        "messages":      [HumanMessage(content="[EnvBuilderAgent] env ready — approved")],
    }


def executor_node(state: GraphState) -> dict[str, Any]:
    log.info("━" * 60); log.info("NODE  executor_node  [Stage 4 — Code Generation]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    factory.display_agent_file("EXECUTOR")
    _approval_gate("executor:agent_file", "Approve CLAUDE_EXECUTOR.md? [approve/reject]: ")

    skills = _skills_for(state, "execute")
    agent  = factory.spawn("EXECUTOR", stage="execute", inject_mcp=True, skills=skills,
                           memories=_memories_for(state))
    raw    = agent.invoke(
        f"Activity:\n{state['activity']}\n\nPlan:\n{state['plan']}\n\n"
        f"Spec:\n{state['spec']}\n\nrequirements.txt:\n{state['requirements']}"
        + _rag_codebase_context(
            state, f"{state['activity']}\n{state['spec'][:800]}", "EXECUTOR", k=8)
    )

    source_files = parse_file_blocks(raw)

    # preview before approval
    listing = "\n".join(f"  • {k}  ({len(v)} chars)" for k, v in source_files.items())
    print(f"\n── Generated files ({len(source_files)}) ──\n{listing}\n")

    _approval_gate("executor:output", "Approve generated source files? [approve/reject]: ")

    # write to projects/<id>/src/ only after approval
    project_dir = Path(state["project_dir"])
    src_dir     = project_dir / "src"
    for rel_path, content in source_files.items():
        dest = src_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        log.info("Written: %s", dest)

    elapsed = time.perf_counter() - t0
    return {
        "source_files":  source_files,
        "agents_spawned": factory.total_spawned,
        "agent_log":     state.get("agent_log", []) + [
            {"id": "EXECUTOR", "model": WORKER_MODEL, "stage": "execute", "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":     state.get("approvals", []) + ["executor:approved"],
        "stage_timings": {**state.get("stage_timings", {}), "execute": round(elapsed, 2)},
        "messages":      [HumanMessage(content=f"[ExecutorAgent] {len(source_files)} files — approved")],
    }


def tester_node(state: GraphState) -> dict[str, Any]:
    """Stage 5 — Testing. Runs after code generation and before the app is
    launched: a TESTER agent writes a pytest suite and a launch-risk report,
    and every generated .py file is syntax-checked with py_compile."""
    log.info("━" * 60); log.info("NODE  tester_node  [Stage 5 — Testing]"); log.info("━" * 60)
    t0 = time.perf_counter(); _check_budget()
    factory = _get_factory()

    factory.display_agent_file("TESTER")
    _approval_gate("tester:agent_file", "Approve CLAUDE_TESTER.md? [approve/reject]: ")

    # Give the tester the actual generated sources (truncated per file to stay
    # inside the worker's context budget).
    sources = "\n\n".join(
        f"### FILE: {path}\n```\n{content[:4000]}\n```"
        for path, content in state.get("source_files", {}).items()
    )

    skills = _skills_for(state, "test")
    agent  = factory.spawn("TESTER", stage="test", skills=skills,
                           memories=_memories_for(state))
    raw    = agent.invoke(
        f"Activity:\n{state['activity']}\n\nSpec:\n{state['spec']}\n\n"
        f"Generated source files:\n{sources}"
        + _rag_codebase_context(
            state, f"tests validation edge cases {state['activity']}", "TESTER")
    )

    test_files, test_report = parse_test_output(raw)

    # Machine check on top of the LLM review: compile every generated .py file.
    project_dir = Path(state["project_dir"])
    src_dir     = project_dir / "src"
    errors      = syntax_check(src_dir) if src_dir.exists() else []
    verdict     = (
        "## Syntax check (py_compile)\n\n"
        + ("All generated .py files compile cleanly. ✔\n" if not errors
           else "**Launch blockers — files that do not compile:**\n\n"
                + "\n".join(f"- `{e}`" for e in errors) + "\n")
    )
    full_report = f"{verdict}\n## Tester agent report\n\n{test_report}"
    (project_dir / "test_report.md").write_text(
        f"# Test Report: {state['activity']}\n\n{full_report}", encoding="utf-8"
    )

    listing = "\n".join(f"  • {k}  ({len(v)} chars)" for k, v in test_files.items()) or "  (none)"
    print(f"\n── Test files ({len(test_files)}) ──\n{listing}\n")
    if errors:
        print("── Syntax errors found ──")
        for e in errors:
            print(f"  ✗ {e}")
        print()

    _approval_gate("tester:output", "Approve test suite + report (gates app launch)? [approve/reject]: ")

    # write tests to src/tests/ only after approval
    for rel_path, content in test_files.items():
        dest = src_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        log.info("Written: %s", dest)

    elapsed = time.perf_counter() - t0
    return {
        "test_files":    test_files,
        "test_report":   full_report,
        "agents_spawned": factory.total_spawned,
        "agent_log":     state.get("agent_log", []) + [
            {"id": "TESTER", "model": WORKER_MODEL, "stage": "test", "elapsed_s": round(elapsed, 2)}
        ],
        "approvals":     state.get("approvals", []) + ["tester:approved"],
        "stage_timings": {**state.get("stage_timings", {}), "test": round(elapsed, 2)},
        "messages":      [HumanMessage(content=f"[TesterAgent] {len(test_files)} test files, "
                                               f"{len(errors)} syntax errors — approved")],
    }


def skill_writer_node(state: GraphState) -> dict[str, Any]:
    """Post-run skill generation. Reached only when no skill card matched the
    activity — the pipeline ran on generic agentic capability, so a SKILL_WRITER
    agent distils this run's domain into a new SKILL_*.md for future runs.
    Best-effort: never fails a completed pipeline. No approval gate — the card
    only affects future runs and can be edited/deleted in skills/ at any time."""
    log.info("━" * 60); log.info("NODE  skill_writer_node  [Stage 5 — Skill Generation]"); log.info("━" * 60)
    t0 = time.perf_counter()
    factory = _get_factory()
    sf      = _get_skill_factory()

    if factory.budget_remaining < 1:
        log.warning("Skipping skill generation — agent budget exhausted.")
        return {"generated_skill": ""}

    log.info("No skill card matched this activity — generating one from the run outputs.")
    existing = "\n".join(f"- {s.skill_id}: {s.description}" for s in sf.available()) or "(none)"

    generated = ""
    try:
        agent = factory.spawn("SKILL_WRITER", stage="skill_gen")
        raw   = agent.invoke(
            f"Activity:\n{state['activity']}\n\nPlan:\n{state['plan']}\n\n"
            f"Spec:\n{state['spec']}\n\n"
            f"Existing skill cards (do NOT duplicate these domains):\n{existing}"
        )
        parsed      = parse_skill_card(raw)
        project_dir = Path(state["project_dir"])
        if parsed is None:
            log.warning("SKILL_WRITER output not parseable — raw saved for review.")
            (project_dir / "skill_card_raw.md").write_text(raw, encoding="utf-8")
        else:
            skill_id, card = parsed
            path      = sf.register_card(skill_id, card)
            generated = path.stem.replace("SKILL_", "")
            ap = project_dir / "skills_assigned.json"
            assignments = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else {}
            assignments["generated_skill"] = generated
            ap.write_text(json.dumps(assignments, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Skill generation failed (pipeline output unaffected): %s", exc)

    elapsed = time.perf_counter() - t0
    return {
        "generated_skill": generated,
        "agents_spawned":  factory.total_spawned,
        "agent_log":       state.get("agent_log", []) + [
            {"id": "SKILL_WRITER", "model": WORKER_MODEL, "stage": "skill_gen", "elapsed_s": round(elapsed, 2)}
        ],
        "stage_timings":   {**state.get("stage_timings", {}), "skill_gen": round(elapsed, 2)},
        "messages":        [HumanMessage(content=f"[SkillWriterAgent] new skill: {generated or '(none)'}")],
    }

