# LangChain + LangGraph Orchestrator v2
## With user prompt, 10-agent budget & HITL approval gates

---

## What's new in v2

| Feature | Detail |
|---|---|
| User prompt input | Activity entered interactively at startup — no `--activity` flag |
| Agent budget | Hard cap of **10 agents** per run; `BudgetExhaustedError` on overflow |
| Agent file display | Full `CLAUDE_*.md` printed to terminal before agent is spawned |
| HITL approval | `interrupt()` suspends graph at every gate; user types `approve`/`reject` |
| Approval history | Every decision recorded in `GraphState.approvals` and `audit_log.json` |
| Checkpoint resume | `--resume` restores MemorySaver state after a rejected/crashed run |

---

## Architecture

```
orchestrator.py
│
├── AgentFactory                  reads CLAUDE_*.md → spawns _EphemeralAgent
│     ├── budget counter          MAX_AGENTS = 10 (hard cap)
│     ├── display_agent_file()    prints full .md to terminal before spawn
│     └── _EphemeralAgent         LangChain chain: ChatPromptTemplate | ChatAnthropic
│                                 torn down after exactly one .invoke() call
│
├── GraphState (TypedDict)        shared state: plan, spec, requirements,
│                                 source_files, agents_spawned, agent_log, approvals
│
├── LangGraph StateGraph + MemorySaver
│     START
│       │
│       ▼
│     planner_node     ─── interrupt(agent_file) ──▶ user approves .md
│       │              ─── interrupt(output)     ──▶ user approves plan
│       ▼
│     spec_writer_node ─── interrupt(agent_file) ──▶ user approves .md
│       │              ─── interrupt(output)     ──▶ user approves spec
│       ▼
│     env_builder_node ─── interrupt(agent_file) ──▶ user approves .md
│       │              ─── interrupt(output)     ──▶ user approves env files
│       ▼
│     executor_node    ─── interrupt(agent_file) ──▶ user approves .md
│       │              ─── interrupt(output)     ──▶ user approves source files
│       ▼
│     END
│
└── run_with_approvals()          drives the graph through all interrupt() gates
                                  collects user input(), resumes with Command(resume=...)
```

---

## Approval flow (per stage)

```
Stage N
  │
  ├─ 1. display_agent_file("AGENT_ID")   ← full CLAUDE_*.md printed to terminal
  │
  ├─ 2. interrupt(agent_file)            ← graph suspends, state checkpointed
  │      user types: approve / reject
  │
  ├─ 3. AgentFactory.spawn("AGENT_ID")  ← LangChain agent created
  │      agent.invoke(user_message)     ← API call
  │      agent._teardown()              ← agent nulled and GC'd
  │
  ├─ 4. output written to disk (plan.md / spec.md / requirements.txt / source files)
  │
  ├─ 5. interrupt(output)               ← graph suspends, state checkpointed
  │      output printed to terminal (first 80 lines)
  │      user types: approve / reject
  │
  └─ 6. state delta returned → GraphState updated → next node
```

If the user types `reject` at any gate, `ApprovalRejectedError` is raised and the pipeline stops with exit code 3. Run with `--resume` to start from the last checkpoint.

---

## Agent budget

`MAX_AGENTS = 10` is a module-level constant in `orchestrator.py`.

Each `AgentFactory.spawn()` call increments `_total_spawned`. When `_total_spawned >= MAX_AGENTS`, `BudgetExhaustedError` is raised immediately (exit code 2).

The current pipeline uses **4 agents** (one per stage), leaving 6 slots available for future worker agents.

Budget is tracked in `GraphState.agents_spawned` and logged to `audit_log.json`.

---

## Setup

```bash
# 1. Install Python dependencies
pip install langgraph langchain-anthropic langchain-core anthropic python-dotenv

# 2. Credentials
cp .env.example .env
# edit .env — at minimum set ANTHROPIC_API_KEY

# 3. Node.js (optional — for MCP servers)
node --version   # must be >= 18
```

---

## Usage

```bash
# Interactive run — prompts for activity at startup
python orchestrator.py

# Custom output directory
python orchestrator.py --output ./my_project

# Skip .venv creation
python orchestrator.py --no-venv

# Resume from last MemorySaver checkpoint (after rejection or crash)
python orchestrator.py --resume

# List available agent definitions
python orchestrator.py --list-agents
```

---

## File structure

```
lc_lg_orchestrator_v2/
├── orchestrator.py              main entry point
├── mcp_config.json              MCP server definitions
├── .env.example                 copy to .env
├── README.md
└── claude_agents/
    ├── CLAUDE_PLANNER.md        PlannerAgent identity card
    ├── CLAUDE_SPEC_WRITER.md    SpecWriterAgent identity card
    ├── CLAUDE_ENV_BUILDER.md    EnvBuilderAgent identity card
    └── CLAUDE_EXECUTOR.md       ExecutorAgent identity card
```

After a run, `project_output/` contains:

```
project_output/
├── plan.md
├── spec.md
├── requirements.txt
├── setup_env.sh
├── audit_log.json          ← agents spawned, approvals, timings, file list
├── .venv/
└── <generated source files>
```

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Pipeline completed successfully |
| 2 | `BudgetExhaustedError` — 10-agent limit hit |
| 3 | `ApprovalRejectedError` — user rejected a stage |
