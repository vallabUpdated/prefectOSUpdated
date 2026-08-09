# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Shared LangGraph state."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ─────────────────────────────────────────────────────────────────────────────

class GraphState(TypedDict):
    activity:       str
    project_dir:    str           # ← unique per request
    thread_id:      str           # ← unique per request, used for checkpoint key
    skip_venv:      bool
    existing_codebase: str        # ← optional path to a legacy codebase to comprehend first
    comprehension:  str           # ← architecture/rules/risk analysis produced by comprehender_node

    plan:           str
    spec:           str
    env_script:     str
    requirements:   str
    source_files:   dict[str, str]
    test_files:     dict[str, str]  # ← pytest files written by the tester stage
    test_report:    str             # ← tester's static review / launch-risk report
    generated_skill: str          # ← skill card created post-run when no skill matched

    agents_spawned: int
    agent_log:      list[dict]
    approvals:      list[str]
    stage_timings:  dict[str, float]
    messages:       Annotated[list[BaseMessage], add_messages]


