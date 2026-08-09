# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Graph wiring (StateGraph) and the interrupt-driving CLI runner."""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .config import log
from .errors import ApprovalRejectedError
from .state import GraphState
from .runtime import _get_skill_factory
from .nodes import (comprehender_node, planner_node, spec_writer_node,
                    env_builder_node, executor_node, tester_node,
                    skill_writer_node)

# ─────────────────────────────────────────────────────────────────────────────

def route_after_tester(state: GraphState) -> str:
    """If the skill factory had nothing to offer this activity, detour through
    skill_writer_node to grow the factory; otherwise finish normally."""
    if _get_skill_factory().match(state["activity"]):
        return END
    return "skill_writer"


def build_graph(checkpointer: MemorySaver):
    graph = StateGraph(GraphState)
    graph.add_node("comprehender", comprehender_node)
    graph.add_node("planner",      planner_node)
    graph.add_node("spec_writer",  spec_writer_node)
    graph.add_node("env_builder",  env_builder_node)
    graph.add_node("executor",     executor_node)
    graph.add_node("tester",       tester_node)
    graph.add_node("skill_writer", skill_writer_node)
    graph.add_edge(START,          "comprehender")
    graph.add_edge("comprehender", "planner")
    graph.add_edge("planner",      "spec_writer")
    graph.add_edge("spec_writer",  "env_builder")
    graph.add_edge("env_builder",  "executor")
    graph.add_edge("executor",     "tester")
    graph.add_conditional_edges("tester", route_after_tester,
                                {END: END, "skill_writer": "skill_writer"})
    graph.add_edge("skill_writer", END)
    return graph.compile(checkpointer=checkpointer)




# ─────────────────────────────────────────────────────────────────────────────

def run_with_approvals(app, initial_state: GraphState, config: dict) -> GraphState:
    from langgraph.types import Command

    result = app.invoke(initial_state, config=config)

    while True:
        snapshot = app.get_state(config)
        if not snapshot.tasks:
            break

        pending = []
        for task in snapshot.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                pending.extend(task.interrupts)
        if not pending:
            break

        for irpt in pending:
            value  = irpt.value if hasattr(irpt, "value") else irpt
            prompt = value.get("prompt", "Decision [approve/reject]: ") if isinstance(value, dict) else str(value)
            content = value.get("content", "") if isinstance(value, dict) else ""

            if content:
                print(f"\n── Preview ──")
                for i, line in enumerate(content.splitlines()[:80], 1):
                    print(f"  {i:>4}  {line}")
                print()

            while True:
                try:
                    decision = input(f"  ▶ {prompt}").strip().lower()
                except EOFError:
                    decision = "approve"
                if decision in ("approve", "reject"):
                    break
                print("  Please type 'approve' or 'reject'.")

            result = app.invoke(Command(resume=decision), config=config)

    return result if isinstance(result, dict) else app.get_state(config).values


