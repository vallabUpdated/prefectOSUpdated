import React from "react";

const obligations = [
  { rule: "Customer data retention", owner: "Data Platform", risk: "High", status: "Impact mapped" },
  { rule: "Claims decision explainability", owner: "Insurance Ops", risk: "High", status: "Controls drafted" },
  { rule: "KYC refresh frequency", owner: "Onboarding", risk: "Medium", status: "Stories generated" },
  { rule: "Payment dispute SLA", owner: "Payments", risk: "Medium", status: "Approval pending" },
];

const workflow = [
  "Ingest circular / policy / audit finding",
  "Extract obligations and deadlines",
  "Map impacted apps, APIs, data stores, and owners",
  "Generate implementation stories and test evidence plan",
  "Route risk-based approvals",
  "Track remediation and produce audit pack",
];

export default function RegulatoryIntelligence({ onRunRegulatoryTemplate }) {
  return (
    <div className="enterprise-page">
      <section className="enterprise-hero regulatory-hero">
        <div>
          <span className="eyebrow">Regulatory Intelligence</span>
          <h1>Convert regulations into governed delivery work</h1>
          <p>
            Designed for RBI, IRDAI, SEBI, PCI DSS, GDPR, SOC2, ISO 27001, DORA, and internal policy updates.
            The goal is to reduce weeks of manual interpretation into an auditable agent-led workflow.
          </p>
          <button className="primary-action" onClick={onRunRegulatoryTemplate}>Launch regulatory impact run</button>
        </div>
      </section>

      <section className="enterprise-grid two-col">
        <article className="panel-card">
          <h2>Regulation-to-Implementation Pipeline</h2>
          <div className="vertical-steps">
            {workflow.map((item, index) => (
              <div className="vertical-step" key={item}>
                <span>{index + 1}</span>
                <p>{item}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-title-row">
            <h2>Obligation Register</h2>
            <span className="pill warn">Sample regulated backlog</span>
          </div>
          <div className="obligation-table">
            <div className="table-head"><span>Obligation</span><span>Owner</span><span>Risk</span><span>Status</span></div>
            {obligations.map((row) => (
              <div className="table-row" key={row.rule}>
                <span>{row.rule}</span>
                <span>{row.owner}</span>
                <span className={`risk ${row.risk.toLowerCase()}`}>{row.risk}</span>
                <span>{row.status}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel-card">
        <div className="panel-title-row">
          <h2>Domain Agent Team</h2>
          <span className="pill">Compliance + engineering collaboration</span>
        </div>
        <div className="domain-agent-grid">
          {["Regulation Reader", "Compliance Expert", "Impact Analyzer", "Architecture Mapper", "Delivery Planner", "Audit Evidence Builder"].map((name) => (
            <div className="domain-agent" key={name}>{name}</div>
          ))}
        </div>
      </section>
    </div>
  );
}
