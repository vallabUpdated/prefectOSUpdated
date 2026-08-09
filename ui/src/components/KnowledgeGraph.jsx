import React from "react";

const graphNodes = [
  ["Regulation", "RBI KYC Circular"],
  ["Business Process", "Customer Onboarding"],
  ["Application", "Mobile Banking App"],
  ["API", "KYC Verification API"],
  ["Database", "Customer Master DB"],
  ["Control", "PII Masking + Approval Gate"],
  ["Owner", "Compliance + Platform Team"],
];

const useCases = [
  "Which APIs expose customer PII?",
  "Which releases need compliance approval?",
  "Which applications are affected by a new regulation?",
  "Which test evidence supports this audit control?",
  "Which AI agent made this decision and why?",
];

export default function KnowledgeGraph() {
  return (
    <div className="enterprise-page">
      <section className="enterprise-hero graph-hero">
        <div>
          <span className="eyebrow">Enterprise Knowledge Graph</span>
          <h1>Connect applications, data, controls, policies, and AI agents</h1>
          <p>
            Move beyond document search. Prefect OS should understand relationships across enterprise systems,
            regulations, owners, workflows, and agent decisions so impact analysis becomes explainable.
          </p>
        </div>
      </section>

      <section className="enterprise-grid two-col">
        <article className="panel-card graph-panel">
          <h2>Reference Graph</h2>
          <div className="graph-chain">
            {graphNodes.map(([type, label], index) => (
              <React.Fragment key={label}>
                <div className="graph-node">
                  <span>{type}</span>
                  <strong>{label}</strong>
                </div>
                {index < graphNodes.length - 1 && <div className="graph-edge">↓</div>}
              </React.Fragment>
            ))}
          </div>
        </article>

        <article className="panel-card">
          <div className="panel-title-row">
            <h2>Questions the platform can answer</h2>
            <span className="pill success">Enterprise memory</span>
          </div>
          <div className="question-list">
            {useCases.map((item) => <div className="question-card" key={item}>{item}</div>)}
          </div>
        </article>
      </section>
    </div>
  );
}
