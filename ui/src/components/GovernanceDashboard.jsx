import React from "react";

const riskCards = [
  { label: "Audit Readiness", value: "98%", trend: "+4%", tone: "good" },
  { label: "AI Governance", value: "96%", trend: "12 controls", tone: "good" },
  { label: "Open High Risks", value: "3", trend: "needs review", tone: "warn" },
  { label: "Pending Approvals", value: "18", trend: "5 critical", tone: "warn" },
];

const controls = [
  ["Prompt lineage", "Enabled", "Every prompt, model, agent, tool, and output is traceable."],
  ["Sensitive data guard", "Active", "PII and financial data exposure checks before execution."],
  ["Human approval gates", "Risk based", "High-risk workflows require business, compliance, or security sign-off."],
  ["Model registry", "Ready", "Track model purpose, owner, version, cost, and evaluation scores."],
  ["Audit evidence", "Continuous", "Approval records, generated files, test outputs, and decisions are stored."],
];

const agentWorkforce = [
  { name: "Regulation Reader", dept: "Compliance", kpi: "Obligations extracted", score: "94%" },
  { name: "Risk Assessor", dept: "Risk", kpi: "Workflow risk scored", score: "91%" },
  { name: "Security Reviewer", dept: "Security", kpi: "Control violations found", score: "97%" },
  { name: "Release Governor", dept: "Engineering", kpi: "Release gates enforced", score: "99%" },
];

export default function GovernanceDashboard() {
  return (
    <div className="enterprise-page">
      <section className="enterprise-hero governance-hero">
        <div>
          <span className="eyebrow">Enterprise AI Governance OS</span>
          <h1>Control plane for regulated AI agent work</h1>
          <p>
            Prefect OS now presents the orchestration runtime as a governed enterprise platform for banking,
            fintech, insurance, healthcare, telecom, and public-sector teams.
          </p>
        </div>
        <div className="hero-score-card">
          <span>Enterprise Risk Score</span>
          <strong>2.1</strong>
          <small>Low residual risk after controls</small>
        </div>
      </section>

      <section className="metric-grid">
        {riskCards.map((card) => (
          <article key={card.label} className={`metric-card ${card.tone}`}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
            <small>{card.trend}</small>
          </article>
        ))}
      </section>

      <section className="enterprise-grid two-col">
        <article className="panel-card">
          <div className="panel-title-row">
            <h2>Governed AI Transaction Lifecycle</h2>
            <span className="pill success">Live blueprint</span>
          </div>
          <div className="lifecycle-flow">
            {[
              "Prompt intake",
              "Policy validation",
              "Risk scoring",
              "Agent execution",
              "Human approval",
              "Evaluation",
              "Audit evidence",
            ].map((step, index) => (
              <div className="life-step" key={step}>
                <span>{index + 1}</span>
                <p>{step}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-title-row">
            <h2>Control Coverage</h2>
            <span className="pill">SOC2 / ISO / RBI ready</span>
          </div>
          <div className="control-list">
            {controls.map(([name, status, desc]) => (
              <div className="control-row" key={name}>
                <div>
                  <strong>{name}</strong>
                  <p>{desc}</p>
                </div>
                <span>{status}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-card">
        <div className="panel-title-row">
          <h2>AI Agent Workforce</h2>
          <span className="pill">Managed like digital employees</span>
        </div>
        <div className="workforce-grid">
          {agentWorkforce.map((agent) => (
            <article className="workforce-card" key={agent.name}>
              <strong>{agent.name}</strong>
              <span>{agent.dept}</span>
              <p>{agent.kpi}</p>
              <b>{agent.score}</b>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
