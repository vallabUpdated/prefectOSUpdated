# Landing Page Plan 2: Developer-First & Agentic Engineer Centric

> **Target Audience:** AI Engineers, Python Developers, Solutions Architects, Tech Leads building agentic pipelines.
> **Primary Goal:** Drive immediate CLI downloads (`pip install prefect-os`), GitHub stars, and developer API key signups.
> **Visual Theme:** Matrix Terminal Dark (`#090D16`), Cyan Blue (`#38BDF8`), Electric Violet (`#A855F7`), High-contrast Monospace typography.

---

## 1. Executive Strategy & Positioning

Plan 2 targets technical practitioners who want code-level control over agentic workflows. Instead of abstract marketing jargon, this landing page leads with **real code, CLI commands, architecture diagrams, and Python SDK syntax**. It highlights key developer features: 10-agent budget caps, LangGraph state machine integration, custom policy rulebooks, and simple CLI commands.

---

## 2. Page Architecture & Wireframe Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Nav] >_ PrefectOS | Docs | GitHub ⭐ 4.2k | PyPI v2.4 | [Get API Key]  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  [Terminal Prompt: $ pip install prefect-os-core]                       │
│  <h1>Deterministic AI Agent Orchestration in Python.</h1>               │
│  <p>Build fault-tolerant, budget-capped, state-machine agent graphs with │
│     native human-in-the-loop (HITL) checkpoints in under 5 lines.</p>  │
│                                                                         │
│  [ CTA Button: Copy Install Command 📋 ] [ Button: Read Documentation ] │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  # Python SDK Live Code Preview                                   │  │
│  │  from prefect_os import Orchestrator, AgentBudget, interrupt       │  │
│  │  orchestrator = Orchestrator(max_agents=10, memory_saver=True)    │  │
│  │  @orchestrator.node                                               │  │
│  │  def approval_gate(state: GraphState):                            │  │
│  │      return interrupt("User approval required for execution")     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  [ Tech Stack Ticker: LangChain | LangGraph | FastAPI | Pydantic | PyTorch ]│
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SECTION 1: Developer Features & SDK Primitives                          │
│  - 10-Agent Budget Hard Caps (No Runaway API Billing)                   │
│  - MemorySaver State Persistence & Checkpoint Resume                    │
│  - Custom Policy Rulebook Interpreter (`prove_interpreter.py`)           │
│  - MCP (Model Context Protocol) Native Compatibility                     │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SECTION 2: Interactive Code Sandbox & State Machine Diagram            │
│  [ Live Code Switcher: Python | CLI | REST API | GraphState Dict ]      │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  SECTION 3: Benchmark & Performance comparison                         │
│  - 99.9% State Recovery on Pipeline Failure                             │
│  - <50ms Overhead per Agent Node Transition                             │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│  SECTION 4: Open Source Ecosystem & Community Contributors              │
├─────────────────────────────────────────────────────────────────────────┤
│  [ Footer CTA: Start Building in 60 Seconds: pip install prefect-os ]   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Section Breakdown & Copy Blueprint

### Hero Section
- **Headline:** Deterministic AI Agent Orchestration in Python.
- **Subheadline:** Stop debugging runaway agent loops. Prefect OS provides state-machine checkpoints, agent budget caps, and native HITL approval gates for production LangGraph pipelines.
- **Primary CTA:** Quickstart Command (`pip install prefect-os`) with 1-click copy feedback.
- **Secondary CTA:** View GitHub Repo / Star on GitHub.
- **Interactive Component:** Live Tabbed Code Window featuring syntax-highlighted Python code with copy button and runnable terminal output preview.

### Section 1: Core Developer Primitives
- **Budget Control:** `AgentFactory.spawn()` with `MAX_AGENTS = 10` cap prevents runaway token burn.
- **Interrupt Checkpoints:** Native `interrupt(agent_file)` suspends execution state to disk, allowing CLI resume with `--resume`.
- **Typed State Graphs:** Pydantic and TypedDict contracts ensure clean data flow between planner, spec writer, environment builder, and executor nodes.

### Section 2: Interactive Architecture Visualizer
- Mermaid.js interactive flow chart showing how nodes transition from `START -> planner_node -> spec_writer_node -> env_builder_node -> executor_node -> END`.

---

## 4. Key Conversion Strategy & CTAs
- **Primary Target:** Developer adoption via PyPI package and GitHub repository stars.
- **Secondary Target:** Free Tier API Key signup for hosting managed state checkpoints on Prefect Cloud.

---

## 5. Technical Implementation Guidelines
- Prism.js / Shiki code highlighting with dark mode terminal aesthetics.
- Interactive terminal component with typing animation effect.
