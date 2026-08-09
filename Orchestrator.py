"""
Orchestrator.py — backward-compatibility façade.

The 2,200-line monolith was split into the `core/` package for
maintainability. This module re-exports the full public surface so every
existing import (`server.py`, tests, tools) keeps working unchanged:

    core/config.py        env, constants, logging, RAG toggle
    core/errors.py        BudgetExhaustedError, ApprovalRejectedError
    core/state.py         GraphState
    core/registry.py      AgentStatus, AgentRecord, AgentRegistry
    core/projects.py      ProjectManager, detect_server_url
    core/agents.py        _EphemeralAgent, AgentFactory
    core/skills.py        Skill, SkillFactory
    core/memory.py        MemoryRecord, MemoryStore
    core/parsing.py       parse_* helpers, syntax_check
    core/docx_export.py   export_docx
    core/runtime.py       set_run_context, per-run singletons, create_venv
    core/nodes.py         all pipeline nodes, approval gates, RAG context
    core/graph.py         build_graph, run_with_approvals
    core/reporting.py     write_audit, write_output_summary, print_summary
    core/cli.py           parse_args, main

New code should import from `core.<module>` directly. NOTE: for the RAG
toggle, read/write `core.config.RAG_ENABLED` (the name re-exported here is
an import-time snapshot).
"""
from __future__ import annotations

# ── configuration & constants ────────────────────────────────────────────
from core.config import (                                    # noqa: F401
    log, ROOT_DIR, AGENTS_DIR, SKILLS_DIR, MEMORY_ROOT, MCP_CONFIG,
    PROJECTS_ROOT, LLM_PROVIDER, OLLAMA_BASE_URL, WORKER_MODEL,
    SUPERVISOR_MODEL, MAX_AGENTS, RAG_ENABLED,
)

# ── exceptions & state ───────────────────────────────────────────────────
from core.errors import BudgetExhaustedError, ApprovalRejectedError  # noqa: F401
from core.state import GraphState                                    # noqa: F401

# ── domain objects ───────────────────────────────────────────────────────
from core.registry import AgentStatus, AgentRecord, AgentRegistry    # noqa: F401
from core.projects import ProjectManager, detect_server_url          # noqa: F401
from core.agents import AgentFactory, _EphemeralAgent                # noqa: F401
from core.skills import Skill, SkillFactory                          # noqa: F401
from core.memory import MemoryRecord, MemoryStore                    # noqa: F401

# ── helpers ──────────────────────────────────────────────────────────────
from core.parsing import (                                           # noqa: F401
    parse_env_blocks, parse_file_blocks, parse_test_output,
    syntax_check, parse_skill_card,
)
from core.docx_export import export_docx                             # noqa: F401
from core.runtime import (                                           # noqa: F401
    set_run_context, create_venv,
    _get_registry, _get_factory, _get_skill_factory, _get_memory_store,
)

# ── pipeline ─────────────────────────────────────────────────────────────
from core.nodes import (                                             # noqa: F401
    comprehender_node, planner_node, spec_writer_node, env_builder_node,
    executor_node, tester_node, skill_writer_node,
    _approval_gate, _check_budget, _rag_codebase_context,
    _skills_for, _memories_for,
)
from core.graph import build_graph, run_with_approvals, route_after_tester  # noqa: F401
from core.reporting import (                                         # noqa: F401
    write_audit, write_output_summary, print_summary,
)
from core.cli import parse_args, prompt_for_activity, main           # noqa: F401

if __name__ == "__main__":
    main()
