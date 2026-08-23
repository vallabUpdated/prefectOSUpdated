import React from "react";

const SANDBOX_PRESETS = [
  {
    id: "loan_underwriting",
    title: "Automated Loan Underwriting Sandbox",
    badge: "Banking Suite",
    icon: "🏦",
    desc: "Ingests W2, Pay Stubs, and Bank Statements; extracts income & DTI metrics; checks credit policies; routes human approval gate.",
    prompt: "Build an automated loan underwriting pipeline for residential mortgages. Ingest borrower paystubs and W2 documents, extract gross monthly income and debt obligations, calculate debt-to-income ratio (DTI), verify credit policy compliance against Fannie Mae rules, and prompt human approver for underwriting gate approval.",
  },
  {
    id: "kyc_verification",
    title: "KYC & Account Verification Sandbox",
    badge: "Identity Suite",
    icon: "🆔",
    desc: "Parses ID documents, verifies proof of address, checks sanction blacklists, and outputs audit ledger hash entries.",
    prompt: "Build a KYC identity verification and account onboarding workflow. Ingest passport/driver license images and utility bill proof of address, run OCR and extraction, query OFAC and PEP sanction lists, evaluate fraud risk score, and generate signed audit decision ledger entry.",
  },
  {
    id: "regulatory_intelligence",
    title: "Regulatory Circular Impact Sandbox",
    badge: "Compliance Suite",
    icon: "⚖️",
    desc: "Ingests regulatory circulars/updates, maps affected core banking systems & APIs, and calculates risk impact score.",
    prompt: "Build a regulatory intelligence workflow for a fintech/insurance enterprise. Ingest a regulatory circular or policy update, extract obligations, map impacted applications/APIs/databases/business processes, calculate risk score, create implementation tasks, route human approvals, and generate an audit evidence pack.",
  },
  {
    id: "greenfield_orchestrator",
    title: "Greenfield Multi-Agent Codebase Sandbox",
    badge: "Orchestration Engine",
    icon: "⚡",
    desc: "Spawns 4 specialized agents (Planner, Spec Writer, Environment Builder, Executor) to build custom microservices.",
    prompt: "Build a secure REST API microservice in Python FastAPI with JWT authentication, PostgreSQL database connection, rate limiting, and comprehensive unit tests.",
  },
];

export default function ClientSandboxModal({ open, onClose, onLaunchDemo }) {
  if (!open) return null;

  const handleSelectPreset = (preset) => {
    onLaunchDemo(preset.prompt);
    onClose();
  };

  return (
    <div className="auth-backdrop" onClick={onClose}>
      <div className="auth-modal sandbox-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-close-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>

        <div className="sec-modal-header">
          <div className="sec-shield-icon">🚀</div>
          <h2>Interactive Client Sandbox Environment</h2>
          <p>Select a pre-configured enterprise workflow sandbox to test live multi-agent orchestration.</p>
        </div>

        <div className="sandbox-presets-list">
          {SANDBOX_PRESETS.map((preset) => (
            <div
              key={preset.id}
              className="sandbox-preset-card"
              onClick={() => handleSelectPreset(preset)}
            >
              <div className="sp-header">
                <span className="sp-icon">{preset.icon}</span>
                <div className="sp-title-group">
                  <div className="sp-title-row">
                    <h4 className="sp-title">{preset.title}</h4>
                    <span className="sp-badge">{preset.badge}</span>
                  </div>
                  <p className="sp-desc">{preset.desc}</p>
                </div>
              </div>
              <div className="sp-action-row">
                <span className="sp-launch-lbl">Click to Launch Guided Sandbox →</span>
              </div>
            </div>
          ))}
        </div>

        <div className="sec-actions" style={{ marginTop: 16 }}>
          <button className="sec-btn-secondary" onClick={onClose} style={{ width: "100%" }}>
            Cancel
          </button>
        </div>

        <div className="auth-footer-note">
          ⚡ Live SSE Telemetry · 10-Agent Budget Guardrail Active · Zero Data Retention
        </div>
      </div>
    </div>
  );
}
