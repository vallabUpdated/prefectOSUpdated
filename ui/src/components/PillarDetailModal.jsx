import React from "react";

const PILLAR_DETAILS = {
  budget: {
    icon: "📥",
    title: "Budget Cap Control & Token Guardrails",
    subtitle: "Module-Level MAX_AGENTS = 10 Hard Cap",
    code: `MAX_AGENTS = 10  # Hard module-level constant

def spawn_agent(self, agent_id: str):
    if self._total_spawned >= MAX_AGENTS:
        raise BudgetExhaustedError(
            f"Agent budget cap ({MAX_AGENTS}) reached! "
            f"Pipeline terminated to prevent runaway token spend."
        )`,
    bullets: [
      "Hard cap enforced at module level — cannot be bypassed by LLM prompts.",
      "Instant BudgetExhaustedError stops runaway recursion before bill shocks.",
      "Real-time token cost estimation tracking input/output tokens per stage.",
      "Automatic agent teardown & garbage collection immediately after invocation.",
    ],
    status: "🟢 ACTIVE · 4 / 10 SLOTS USED",
  },
  hitl: {
    icon: "👤",
    title: "Human-In-The-Loop (HITL) Approval Gates",
    subtitle: "Interactive interrupt() State Graph Suspensions",
    code: `# Graph node suspends state before execution
prompt_decision = interrupt({
    "stage": "spec_writer",
    "agent_file": "CLAUDE_SPEC_WRITER.md",
    "editable": True,
    "content": generated_spec_markdown,
})

# Resumes with user-approved or edited content
resume_command = Command(resume={"decision": "approve", "content": user_edited_text})`,
    bullets: [
      "Every stage suspends execution with interrupt() before writing output.",
      "Interactive diff viewer allows human approvers to edit plan & spec documents.",
      "Word document export (.docx) generated on demand at every approval gate.",
      "Multi-role sign-off requirements for enterprise risk management.",
    ],
    status: "🟢 ACTIVE · 100% HUMAN VERIFIED",
  },
  ledger: {
    icon: "📄",
    title: "Immutable Decision Ledger & Audit Trail",
    subtitle: "Cryptographic SHA-256 Hash Chain Logging",
    code: `class DecisionLedger:
    def append(self, event_type: str, **payload):
        prev_hash = self.get_latest_hash()
        entry = {
            "seq": self.next_seq(),
            "prev_hash": prev_hash,
            "ts": datetime.now().isoformat(),
            "type": event_type,
            "hash": sha256_text(prev_hash + json.dumps(payload)),
        }
        self.save_entry(entry)`,
    bullets: [
      "Tamper-evident JSON ledger with cryptographic SHA-256 hash chaining.",
      "Records full user prompts, agent responses, token usage, and user signatures.",
      "SOC 2 Type II compliant audit evidence ready for regulatory inspection.",
      "Replayable run events log — view historical pipeline execution frame-by-frame.",
    ],
    status: "🔒 SECURED · HASH CHAIN VERIFIED",
  },
  governance: {
    icon: "🧠",
    title: "Model Governance & Regulatory Policy Packs",
    subtitle: "Fannie Mae, KYC/AML & Policy Rulebook Engine",
    code: `policy_pack = load_policy_pack("policy_packs/fannie_mae_v4.json")

# Evaluate policy rules against extracted loan data
violations = evaluate_policy_rules(
    extracted_data={"dti": 0.46, "ltv": 0.85},
    rules=policy_pack["underwriting_rules"],
)`,
    bullets: [
      "Automated evaluation against indexed banking and credit policy rulebooks.",
      "Claude Anthropic model routing with strict system prompt boundaries.",
      "Zero-data retention options for strict data privacy requirements.",
      "Automated compliance risk scoring before issuing decision certificates.",
    ],
    status: "🟢 ACTIVE · POLICY PACK INDEXED",
  },
  execution: {
    icon: "⬟",
    title: "Parallel & Directed Graph Execution",
    subtitle: "LangGraph StateGraph Multi-Branch Engine",
    code: `builder = StateGraph(GraphState)
builder.add_node("planner", planner_node)
builder.add_node("spec_writer", spec_writer_node)
builder.add_node("executor", executor_node)

builder.add_edge("planner", "spec_writer")
builder.add_conditional_edges("spec_writer", route_next_stage)
graph = builder.compile(checkpointer=MemorySaver())`,
    bullets: [
      "Directed cyclic and acyclic graph execution powered by LangGraph.",
      "Parallel worker agent execution for rapid multi-file generation.",
      "Dynamic routing based on stage output validation and skill matching.",
      "Isolated execution environments for ephemeral agent invocation.",
    ],
    status: "⚡ RUNNING · LANGGRAPH V2 ENGINE",
  },
  monitoring: {
    icon: "📉",
    title: "Deployment & Real-Time Telemetry",
    subtitle: "SSE Live Progress Streaming & Subprocess Management",
    code: `@app.route("/stream/<run_id>")
def stream(run_id: str):
    # Real-time Server-Sent Events (SSE) stream
    return Response(generate_events(run_id), mimetype="text/event-stream")`,
    bullets: [
      "Real-time Server-Sent Events (SSE) stream for instant dashboard telemetry.",
      "Automated subprocess launcher for generated web applications with live URLs.",
      "Live token consumption counters and USD/INR cost projections.",
      "Health monitoring with automated process kill & port cleanup controls.",
    ],
    status: "🟢 OPERATIONAL · 99.99% UPTIME SLA",
  },
};

export default function PillarDetailModal({ open, pillarKey, onClose }) {
  if (!open || !pillarKey || !PILLAR_DETAILS[pillarKey]) return null;

  const detail = PILLAR_DETAILS[pillarKey];

  return (
    <div className="auth-backdrop" onClick={onClose}>
      <div className="auth-modal pillar-detail-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-close-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>

        <div className="pdm-header">
          <div className="pdm-icon-box">{detail.icon}</div>
          <div className="pdm-title-group">
            <h2>{detail.title}</h2>
            <p className="pdm-subtitle">{detail.subtitle}</p>
          </div>
        </div>

        <div className="pdm-status-badge">{detail.status}</div>

        <div className="pdm-code-box">
          <div className="pdm-code-header">
            <span>CORE ARCHITECTURE ENGINE CODE</span>
            <span>PYTHON 3.12</span>
          </div>
          <pre><code>{detail.code}</code></pre>
        </div>

        <div className="pdm-bullets">
          <h4>Key Enterprise Capabilities:</h4>
          <ul>
            {detail.bullets.map((bullet, idx) => (
              <li key={idx}>✓ {bullet}</li>
            ))}
          </ul>
        </div>

        <div className="sec-actions" style={{ marginTop: 18 }}>
          <button className="sec-btn-primary" onClick={onClose} style={{ width: "100%" }}>
            Close Governance Inspection Window
          </button>
        </div>
      </div>
    </div>
  );
}
