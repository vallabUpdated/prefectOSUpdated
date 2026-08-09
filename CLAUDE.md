# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
pip install -r requirements.txt      # or: pip install -e .  (uv.lock / pyproject.toml also present)
cp .env.example .env
# Add ANTHROPIC_API_KEY and any optional keys (GITHUB_TOKEN, DATABASE_URL, etc.)
```

`requirements.txt` / `pyproject.toml` only cover the core pipeline (`langgraph`, `langchain-anthropic`,
`langchain-core`, `anthropic`, `python-dotenv`). The web layer needs extra packages that are **not** in
either dependency file — install manually depending on which backend you run:

```bash
pip install flask flask-cors                       # for server.py (Flask backend — matches current Orchestrator.py)
pip install fastapi "uvicorn[standard]" sse-starlette psutil   # for api.py (FastAPI backend — currently stale, see below)
```

No lint or test framework is configured.

## Running

```bash
python Orchestrator.py                     # interactive CLI — prompts for activity, runs full pipeline
python Orchestrator.py --no-venv           # skip .venv creation in env_builder stage
python Orchestrator.py --list-agents       # print all claude_agents/CLAUDE_*.md definitions
python Orchestrator.py --list-skills       # print all skills/SKILL_*.md skill cards
python Orchestrator.py --list-memories     # print memory/ records of past completed runs
python Orchestrator.py --list-projects     # list all past runs under projects/

python server.py                           # Flask web UI backend, serves ui.html, port 5055 by default
python server.py --port 8080
```

`main.py` is an unrelated uv/`pyproject.toml` scaffold stub ("Hello from lc-lg-orchestrator-v2!") — not part
of the orchestrator pipeline.

## Architecture

This repo has two layers:

1. **Core pipeline** — `Orchestrator.py` (note the capital "O"; this is the only orchestrator module that
   exists). A 4-stage LangGraph pipeline that turns a natural-language activity description into a plan,
   spec, environment, and generated source code, gated by human-in-the-loop approval at every step.
2. **Web layer** — `server.py` + `ui.html` (Flask, current/working) and `api.py` (FastAPI, **stale**), both
   of which wrap the same pipeline and stream live events to a dashboard over SSE.

### Pipeline (LangGraph StateGraph, `Orchestrator.py`)

```
User input (activity)
  → planner_node     → plan.md                          → HITL approval
  → spec_writer_node → spec.md                           → HITL approval
  → env_builder_node → requirements.txt + setup_env.sh   → HITL approval → .venv creation
  → executor_node    → source files                      → HITL approval → write to disk
  → tester_node      → src/tests/ + test_report.md       → HITL approval (gates app launch)
  → (skill_writer_node — only when no skill card matched; no approval gate)
```

`tester_node` (stage `test`, `CLAUDE_TESTER.md`) generates a pytest suite and a launch-risk report from
the generated sources, plus a `py_compile` syntax check of every generated `.py` file
(`syntax_check()`); its output parser is `parse_test_output()` (same `### FILE:` blocks as the executor
plus a `### TEST REPORT` section). Test files are written to `src/tests/` after approval.

Each node calls `factory.display_agent_file()`, gates on `interrupt()` for the agent-file approval, spawns
an `_EphemeralAgent` and invokes it once, writes the output to disk, gates on a second `interrupt()` for
output approval, then returns a state delta.

**Editable document gates**: the `planner:output` and `spec_writer:output` gates are *editable* —
`_approval_gate(stage, prompt, content=..., editable=True)` puts the full document in the interrupt
payload, and the resume value may be `{"decision": "approve", "content": <edited text>}` instead of a
plain `"approve"`/`"reject"` string. Edits become the official plan/spec: state and `plan.md`/`spec.md`
are rewritten before the next stage runs. In the web UI this renders as a Word-style editable document
page (React `ApprovalGate.jsx`; the edited text is POSTed via `/approve` `content` field). In the CLI,
edit `projects/<id>/plan.md` / `spec.md` on disk while the run is paused at the gate — the node re-reads
the file (minus its `# Plan:`/`# Spec:` header) after approval. Note the legacy `ui.html` fallback does
not have the editor.

**Word export**: after each plan/spec approval, the final (post-edit) document is also exported as
`projects/<id>/plan.docx` / `spec.docx` via `export_docx()` (markdown → Word: headings, bullet/numbered
lists, fenced code, bold/inline code; requires `python-docx`, best-effort if missing). The web UI shows a
"⬇ .docx" download link on the document page during approval, served by `GET /docx/<run_id>/<plan|spec>`
in `server.py`, which regenerates the file from the markdown on demand.

### Per-request project isolation

Every run gets its own directory under `projects/<YYYYMMDD_HHMMSS>_<slug>/` (created by `ProjectManager`)
and its own LangGraph `thread_id` (same string as the directory name), so checkpoints from concurrent or
past runs never collide. Each project directory ends up with `project.json` (manifest), `plan.md`,
`spec.md`, `requirements.txt`, `setup_env.sh`, `agent_registry.json`, `audit_log.json`,
`generated_output.txt`, `.venv/`, and generated source under `src/`.

`logistics_app/`, `medical_app/`, and `policy_center/` at the repo root are **output artifacts** from past
pipeline runs (each has its own `app.py`, `db.py`, a `.db` SQLite file, `templates/`, `static/`) — not part
of the orchestrator's own source. Treat them as generated projects, not framework code.

### Key Classes (all in `Orchestrator.py`)

- **`AgentRegistry`** — tracks every agent's lifecycle (`PENDING → ALIVE → TORN_DOWN`/`FAILED`), prints an
  ASCII table to the terminal on every transition, and persists to `agent_registry.json`.
- **`ProjectManager`** — creates/lists the timestamped `projects/<id>/` directories described above.
- **`GraphState` (TypedDict)** — state threaded through all nodes: `activity`, `project_dir`, `thread_id`,
  `skip_venv`, `plan`, `spec`, `env_script`, `requirements`, `source_files`, `agents_spawned`, `agent_log`,
  `approvals`, `stage_timings`, `messages`.
- **`_EphemeralAgent`** — wraps a `ChatPromptTemplate | ChatAnthropic` chain, reports ALIVE/TORN_DOWN to the
  registry, torn down (all references nulled) immediately after its single `.invoke()` call.
- **`AgentFactory`** — reads `claude_agents/CLAUDE_*.md`, enforces the global budget (`MAX_AGENTS = 10`,
  raises `BudgetExhaustedError` at the cap), registers each spawn with the `AgentRegistry`, and optionally
  injects MCP server context (`inject_mcp=True`) into the executor agent.
- **`_approval_gate()`** — thin wrapper around LangGraph's `interrupt()`; raises `ApprovalRejectedError` if
  the resumed value is `"reject"`.

### Agent Role Cards (`claude_agents/`)

| File | Role | Output format |
|------|------|---------------|
| `CLAUDE_PLANNER.md` | Senior project planner | Plain markdown |
| `CLAUDE_SPEC_WRITER.md` | Technical spec writer | Plain markdown |
| `CLAUDE_ENV_BUILDER.md` | DevOps / Python specialist | Labelled bash + text blocks |
| `CLAUDE_EXECUTOR.md` | Senior software engineer | `### FILE: path` blocks |
| `CLAUDE_TESTER.md` | QA engineer (stage 5, before app launch) | `### FILE: tests/…` blocks + `### TEST REPORT` |
| `CLAUDE_SKILL_WRITER.md` | Skill card author (runs only on skill-gap runs) | `SKILL_ID:` line + fenced markdown card |

### Skill Factory (`skills/`)

`SkillFactory` (in `Orchestrator.py`) loads `skills/SKILL_*.md` cards and matches them against the
user's activity prompt by keyword (word-boundary, case-insensitive). Matched skills are appended to the
agent's system prompt at spawn time (`AgentFactory.spawn(..., skills=...)`) — every pipeline node calls
`_skills_for(state, stage)` before spawning. Assignments are persisted per run to
`projects/<id>/skills_assigned.json` (stage → skill list). If no keywords match, agents run with just
their base role card.

Each card has YAML-ish frontmatter (`name`, `description`, `keywords` comma-separated, `stages`
comma-separated subset of `plan, spec, env, execute`) followed by a markdown guidelines body:

| File | Skill | Notes |
|------|-------|-------|
| `SKILL_PYTHON_DEV.md` | Python development | Flask/FastAPI/CLI conventions, PEP 8, typing |
| `SKILL_DOTNET_DEV.md` | .NET development | C#/ASP.NET Core/EF Core conventions |
| `SKILL_FINTECH_MAINTENANCE.md` | Fintech maintenance | Decimal money, double-entry ledgers, idempotency, audit |
| `SKILL_DB_MANAGEMENT.md` | DB creation & maintenance | Schema design, migrations, parameterized queries |
| `SKILL_TESTING.md` | Testing | pytest/xUnit strategy; applies to plan/spec/execute only |

To add a skill, drop a new `SKILL_<ID>.md` in `skills/` — no code changes needed.

**Self-growing factory**: if an activity matches *no* skill card, the pipeline proceeds anyway on the
agents' base role cards, and after the executor stage a conditional edge (`route_after_executor`)
detours through `skill_writer_node` — a 5th agent (`claude_agents/CLAUDE_SKILL_WRITER.md`, stage
`skill_gen`) that distils the run's activity/plan/spec into a new `SKILL_*.md`, registers it via
`SkillFactory.register_card()` (hot-reloaded, filename collisions get `_2` suffixes), and records it
under `generated_skill` in `skills_assigned.json`, `audit_log.json`, and `GraphState`. The node is
best-effort and gate-free: budget exhaustion or agent failure logs a warning and never fails a
completed pipeline; unparseable output (`parse_skill_card()` expects a `SKILL_ID: <ID>` line + fenced
markdown card) is saved to the project dir as `skill_card_raw.md` for manual review.

### Memory Store (`memory/`)

`MemoryStore` (in `Orchestrator.py`) gives agents long-term experience memory across runs, on top of the
other layers (agents themselves are ephemeral and memoryless; `GraphState` + `MemorySaver` is per-run
working memory; `skills/` is learned domain guidance):

- **Record**: on every completed run, `write_audit()` calls `MemoryStore.record_run(state)` (best-effort),
  distilling the run into `memory/<project_id>.json` — activity, assigned skills, requirements, file list,
  plan/spec excerpts, test-report notes, detected server URL.
- **Recall**: every pipeline node calls `_memories_for(state)` → `MemoryStore.recall(activity, k=3)`, which
  ranks past records by stopword-filtered keyword overlap (past activity weighted 3×, skills/requirements/
  files 1×; minimum score cutoff, current run excluded). No embeddings or extra dependencies.
- **Inject**: matches are passed to `AgentFactory.spawn(..., memories=...)` and appended to the system
  prompt as a "Relevant Past Project Experience" section, so agents see how similar past projects were
  planned, what stack they used, and what broke at testing/launch.
- What was recalled is persisted per run to `projects/<id>/memory_recall.json`. Both the CLI and web
  backend get record+recall automatically (the hook lives in shared code; `server.py` needed no changes).

### Output Parsing

- `parse_env_blocks()` — splits env builder output into `setup_env.sh` and `requirements.txt` (falls back
  to `_default_env_script()` / `_default_requirements()` if the expected fenced blocks aren't found).
- `parse_file_blocks()` — parses `### FILE: path/to/file.py` sections from executor output into
  `dict[path, content]`; if none are found, the raw output is saved as `generated_output.txt`.
- `detect_server_url()` — scans generated files (`app.py`, `main.py`, `run.py`, `server.py`, `wsgi.py`) for
  a port via regex (Flask `app.run(port=...)`, FastAPI `uvicorn.run(...)`, `PORT =`, argparse `--port`,
  etc.) so the CLI/UI can print/launch the running app's URL after generation.

### Models

`AgentFactory.spawn()` routes to one of two LLM providers based on `DEFAULT_PROVIDER` in `.env`
(`anthropic` by default, `ollama` for a local server — no API key needed):

- **anthropic**: worker agents (Planner, SpecWriter, EnvBuilder, Executor) use `claude-haiku-4-5`
  (4096 max tokens); optional supervisor override (`spawn(..., supervisor=True)`) uses `claude-sonnet-4-6`.
  Requires `ANTHROPIC_API_KEY`.
- **ollama**: both worker and supervisor default to `qwen2.5:14b` against `OLLAMA_BASE_URL`
  (default `http://localhost:11434`), overridable via `OLLAMA_WORKER_MODEL` / `OLLAMA_SUPERVISOR_MODEL`.
  Note `supervisor=True` is never actually passed anywhere in the current pipeline, so in practice all
  four agents always use `WORKER_MODEL`.

### MCP Integration

`mcp_config.json` defines five optional MCP servers (github, postgres, sqlite, playwright, gmail). When
`inject_mcp=True` is passed to `AgentFactory.spawn()` (used for the executor stage), their connection
details are appended to the agent's system prompt so generated code can integrate with those capabilities.

### Web layer caveats

- `server.py` (Flask, port 5055) imports from `Orchestrator` (capital O) and matches the current pipeline
  exactly — this is the backend that actually works today. Its routes: `/`, `POST /run`,
  `GET /stream/<run_id>`, `POST /approve/<run_id>`, `GET /runs`.
- `api.py` (FastAPI) imports `orchestrator` (lowercase — resolves only because Windows filesystems are
  case-insensitive) and references things that don't exist in `Orchestrator.py` (`orch.VenvManager`,
  `orch.VENVS_ROOT`, `orch.launch_app_node`, an `app_url`/`app_port`/`app_pid` state shape). It will error
  at runtime as-is; treat it as stale/in-progress rather than a working alternative backend.
- `server.py` also implements `/cancel/<run_id>`, `/stop/<run_id>`, and `/app-status/<run_id>`, so all
  `ui.html` buttons work against it.
- **Pause/Resume** (`POST /pause/<run_id>` / `POST /resume/<run_id>`): holds the pipeline thread at the
  next stage/approval boundary via a `threading.Event` gate in `RunContext` (`request_pause()` /
  `request_resume()` / `wait_if_paused()`), emitting `pipeline_paused` / `pipeline_resumed` SSE events.
  Like cancel, pause is cooperative — an in-flight agent call finishes first. Pausing while an approval
  gate is open leaves the gate usable; the decision is held until resume. Cancel always releases a
  paused run. The React top bar (`TopBar.jsx`) shows a Pause/Resume toggle next to "Stop pipeline"
  (React dashboard only; the legacy `ui.html` fallback has no pause button).
- **Parallel runs**: `server.py` supports multiple concurrent pipeline runs, one thread each. The
  per-run bindings that used to be process-wide singletons are context-local (`contextvars`, which
  LangGraph propagates into node execution): `Orchestrator.set_run_context(registry, factory)` binds
  each run thread's registry/factory (the `_registry`/`_factory` module globals remain the CLI
  fallback), and `decision_ledger.activate_ledger()` binds the ledger the same way. Stage-started
  tracking lives on `RunContext.seen_stages` (was a module global). `launch_generated_app()` refuses
  to launch when the target port is already open (another run's app would otherwise make the health
  check report a false "up"). In the React UI the Run button always starts a new parallel run; a run
  switcher strip (`RunSwitcher.jsx`, shown when ≥2 runs exist) selects which run the dashboard panes
  and the approve/pause/stop controls target — each run keeps its own SSE stream and state
  (`usePipelineRun.js` holds a runId-keyed state map). The switcher's "⊞ All runs" toggle opens a
  **board view** (`RunBoard.jsx`): a grid with one card per run (status, stage progress strip,
  tokens/budget, inline Approve/Reject for the open gate, Pause/Resume, Stop, app link) plus a
  "start another run" card; "Open ▸"/chip click returns to the single-run detail view. All hook
  actions accept an optional explicit runId (board cards) and default to the selected run. The
  legacy `ui.html` remains single-run. E2E coverage: `python tests/e2e_stub_server.py` (stubbed-LLM
  backend on :5056) + `python tests/e2e_parallel_runs.py [--headed]` (Playwright; drives two
  parallel runs through switcher, board, pause/resume, and all gates).
- **App launch** (`launch_generated_app()` in `server.py`): after the pipeline completes, the generated
  app is started as a subprocess with output captured to `projects/<id>/app_launch.log` and health-checked
  (process alive + port answering, ~10s window) before `app_launched` is emitted. If the first attempt dies
  with `ModuleNotFoundError`/`ImportError` and the project has no `.venv`, requirements.txt is installed
  into a fresh project venv and the launch is retried once. A dead app is reported as a launch failure with
  the log tail — never as a live URL.

### Exit Codes (`Orchestrator.py` CLI)

| Code | Meaning |
|------|---------|
| 0 | Pipeline completed successfully |
| 2 | `BudgetExhaustedError` — 10-agent cap reached |
| 3 | `ApprovalRejectedError` — user rejected a stage |

## Stage 0 — Legacy Comprehension (optional)

Point a run at an existing codebase and the COMPREHENDER agent analyses it *before* planning:

```bash
python Orchestrator.py --codebase /path/to/legacy/system
# web: POST /run {"activity": "...", "codebase": "/path/to/legacy/system"}
```

`comprehension.py` builds a bounded digest (tree + configs + source excerpts; vendor dirs pruned,
`.env`-style secrets withheld and disclosed). The agent (claude_agents/CLAUDE_COMPREHENDER.md) emits
`architecture.md`, `business_rules.md`, and `risk_register.md` into the project dir, gated by HITL
approval like every other stage. The approved analysis is injected into the Planner's prompt.
With no `--codebase`, comprehender_node is a zero-cost passthrough (no agent slot consumed).

## Decision ledger (tamper-evident provenance)

Every run writes `<project_dir>/decision_ledger.jsonl` — an append-only, SHA-256 hash-chained record
of run start, every gate presented, every human decision (with the exact artifact hash the approver
saw, and whether they edited it), every agent spawn (model, provider, skills, system-prompt hash),
and run completion. `write_audit` verifies the chain and embeds its head hash in `audit_log.json`.

Verify independently:

```bash
python decision_ledger.py verify projects/<run>/decision_ledger.jsonl
```

Any edit, deletion, insertion, or reorder of ledger lines fails verification from that point.
The web UI may attach `{"approver": "<identity>"}` to approval payloads; it is recorded when present
(full maker-checker roles land with the auth layer).
