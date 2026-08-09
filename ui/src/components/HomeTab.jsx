import React from "react";

import { useState } from "react";

const TEMPLATES = [
  {
    id: "regulatory-intelligence",
    title: "Regulatory Impact Analyzer",
    description: "Ingest RBI/IRDAI/PCI/GDPR updates, extract obligations, map impacted systems, create stories, and generate audit evidence.",
    prompt: "Build a regulatory impact analyzer for fintech and insurance teams. It should ingest regulatory circulars, extract obligations, map impacted applications/APIs/databases, calculate risk score, create implementation tasks, route human approvals, and produce an audit evidence pack.",
    gradient: "linear-gradient(135deg, #7c3aed 0%, #2563eb 100%)",
  },
  {
    id: "claims-governance",
    title: "Insurance Claims Governance",
    description: "Govern AI-assisted claims decisions with explainability, fraud signals, approval thresholds, and evidence trails.",
    prompt: "Build an insurance claims governance portal with claim intake, AI recommendation review, fraud signals, risk scoring, human approval gates, explainability notes, and full audit lineage.",
    gradient: "linear-gradient(135deg, #0d9488 0%, #10b981 100%)",
  },
  {
    id: "release-risk-board",
    title: "FinTech Release Risk Board",
    description: "Score releases by compliance, data sensitivity, security findings, test evidence, and business impact before deployment.",
    prompt: "Build a fintech release governance board that evaluates release readiness using test results, security scans, data sensitivity, compliance impact, change approvals, and risk score before allowing deployment.",
    gradient: "linear-gradient(135deg, #d97706 0%, #f59e0b 100%)",
  },
];

const AGENTS = [
  {
    name: "Planner Agent",
    file: "CLAUDE_PLANNER.md",
    role: "Drafts the implementation plan, outlines the file list, and selects standard libraries.",
    color: "var(--purple)",
  },
  {
    name: "Spec Writer Agent",
    file: "CLAUDE_SPEC_WRITER.md",
    role: "Compiles strict architectural specifications, database schemas, and REST endpoints.",
    color: "var(--blue)",
  },
  {
    name: "Env Builder Agent",
    file: "CLAUDE_ENV_BUILDER.md",
    role: "Builds isolated Python environments and installs requirements safely.",
    color: "var(--amber)",
  },
  {
    name: "Executor Agent",
    file: "CLAUDE_EXECUTOR.md",
    role: "Writes high-quality, executable source code files and hooks up integrations.",
    color: "var(--teal)",
  },
  {
    name: "Tester Agent",
    file: "CLAUDE_TESTER.md",
    role: "Writes the pytest suite, syntax-checks generated code, and reports launch blockers before the app starts.",
    color: "var(--red)",
  },
];

export default function HomeTab({ history, onSelectTemplate, onSwitchTab, onCustomBuild }) {
  const [customPrompt, setCustomPrompt] = useState("");
  const [srcKind, setSrcKind] = useState("none");   // none | path | git
  const [cbPath, setCbPath] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [launchErr, setLaunchErr] = useState("");
  // Statistics calculations
  const totalRuns = history.length;
  const successes = history.filter((r) => r.status === "completed").length;
  const failed = history.filter((r) => r.status === "failed" || r.status === "rejected").length;
  const running = history.filter((r) => r.status === "running").length;

  const recentRuns = history.slice(0, 3); // list is already reversed in hook

  // Governed launch → hand prompt + codebase source to the orchestrator
  // (Live Run page, pre-filled for review). Nothing auto-starts from Home.
  const continueToOrchestrator = () => {
    const prompt = customPrompt.trim();
    if (prompt.length < 10) { setLaunchErr("Describe the work first (at least 10 characters)."); return; }
    if (srcKind === "path" && !cbPath.trim()) { setLaunchErr("Enter the codebase folder path, or switch to Greenfield."); return; }
    if (srcKind === "git" && !gitUrl.trim()) { setLaunchErr("Enter the repository URL, or switch to Greenfield."); return; }
    setLaunchErr("");
    const codebase =
      srcKind === "path" ? { source: "path", path: cbPath.trim() }
      : srcKind === "git" ? { source: "git", git_url: gitUrl.trim(), git_branch: gitBranch.trim() || "main" }
      : null;
    onCustomBuild(prompt, codebase);
  };

  return (
    <div id="home-container">
      {/* Hero Header */}
      <header className="home-hero">
        <div className="hero-content">
          <h1>Prefect OS — Enterprise AI Governance</h1>
          <p>
            A regulated-industry control plane for multi-agent delivery, regulatory intelligence, risk scoring, approvals, and continuous audit evidence. 
            Built for fintech, insurance, banking, healthcare, telecom, and government teams.
          </p>
        </div>
        
        {/* Dynamic Stats Grid */}
        <div className="stats-grid">
          <div className="stat-card">
            <span className="stat-value">{totalRuns}</span>
            <span className="stat-label">Governed Runs</span>
          </div>
          <div className="stat-card">
            <span className="stat-value success">{successes}</span>
            <span className="stat-label">Approved Builds</span>
          </div>
          <div className="stat-card">
            <span className="stat-value warning">{running}</span>
            <span className="stat-label">Live Workflows</span>
          </div>
          <div className="stat-card">
            <span className="stat-value danger">{failed}</span>
            <span className="stat-label">Blocked Risks</span>
          </div>
        </div>
      </header>

      {/* ── Governed launch — the front door to the orchestrator ─────────── */}
      <section className="gl-panel">
        <div className="gl-main">
          <div className="gl-title">Start a governed run</div>
          <div className="gl-sub">
            Describe the work, point at the system it touches, and continue to the
            orchestrator — every step from here is gated, budgeted, and ledger-sealed.
          </div>

          <label className="gl-label" htmlFor="gl-prompt">What should the agent team deliver?</label>
          <textarea
            id="gl-prompt"
            className="gl-prompt"
            rows={3}
            placeholder="e.g. Modernize the premium calculation module of our COBOL motor insurance engine while preserving all rating rules"
            value={customPrompt}
            onChange={(e) => setCustomPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); continueToOrchestrator(); }
            }}
          />

          <label className="gl-label">Which system does this touch?</label>
          <div className="gl-src-seg">
            <button className={srcKind === "none" ? "on" : ""} onClick={() => setSrcKind("none")}
              title="Build something new — no existing codebase">
              Greenfield
            </button>
            <button className={srcKind === "path" ? "on" : ""} onClick={() => setSrcKind("path")}
              title="A codebase on this machine — digested and indexed by Stage 0 before planning">
              Folder path
            </button>
            <button className={srcKind === "git" ? "on" : ""} onClick={() => setSrcKind("git")}
              title="GitHub / GitLab / Bitbucket or any git remote — cloned server-side, then comprehended">
              Git repository
            </button>
          </div>

          {srcKind === "path" && (
            <input
              className="gl-input"
              type="text"
              placeholder={"e.g. C:\\clients\\acmebank\\core_ledger"}
              value={cbPath}
              onChange={(e) => setCbPath(e.target.value)}
              spellCheck={false}
            />
          )}
          {srcKind === "git" && (
            <div className="gl-git">
              <input
                className="gl-input"
                type="text"
                placeholder="https://github.com/org/repo.git  (GitHub, GitLab, Bitbucket, or any git URL)"
                value={gitUrl}
                onChange={(e) => setGitUrl(e.target.value)}
                spellCheck={false}
              />
              <input
                className="gl-input gl-branch"
                type="text"
                placeholder="branch"
                value={gitBranch}
                onChange={(e) => setGitBranch(e.target.value)}
                spellCheck={false}
              />
            </div>
          )}
          {srcKind !== "none" && (
            <div className="gl-hint">
              Stage 0 will digest this codebase (credentials withheld, digest hash sealed
              to the ledger) and index it for governed retrieval before any plan is proposed.
            </div>
          )}

          {launchErr && <div className="gl-err">{launchErr}</div>}
          <button className="gl-go" onClick={continueToOrchestrator}>
            Continue to orchestrator →
          </button>
          <div className="gl-go-note">Nothing runs yet — you review the full configuration at the orchestrator first.</div>
        </div>

        {/* ── Governance entries ──────────────────────────────────────────── */}
        <div className="gl-entries">
          <button className="gl-entry" onClick={() => onSwitchTab("ledger")}>
            <div className="gl-entry-icon ledger">⛓</div>
            <div className="gl-entry-body">
              <div className="gl-entry-title">Decision Ledger</div>
              <div className="gl-entry-desc">
                Tamper-evident, hash-chained record of every decision across {totalRuns} run{totalRuns === 1 ? "" : "s"} —
                verify any chain in one click.
              </div>
            </div>
            <span className="gl-entry-arrow">→</span>
          </button>

          <button className="gl-entry" onClick={() => onSwitchTab("stage0")}>
            <div className="gl-entry-icon stage0">◫</div>
            <div className="gl-entry-body">
              <div className="gl-entry-title">Stage 0 · Comprehension</div>
              <div className="gl-entry-desc">
                Architecture, business rules and risk registers extracted from legacy
                codebases — with digest provenance.
              </div>
            </div>
            <span className="gl-entry-arrow">→</span>
          </button>

          <button className="gl-entry" onClick={() => onSwitchTab("history")}>
            <div className="gl-entry-icon history">↻</div>
            <div className="gl-entry-body">
              <div className="gl-entry-title">Run History</div>
              <div className="gl-entry-desc">
                Every past engagement with status, stages and artifacts — {successes} approved,
                {" "}{failed} blocked.
              </div>
            </div>
            <span className="gl-entry-arrow">→</span>
          </button>
        </div>
      </section>

      {/* Main Grid: Left (Templates + Roadmap) / Right (Agents + Recent Runs) */}
      <div className="home-layout">
        <div className="home-left">
          {/* Regulated Industry Launch Templates */}
          <section className="home-section">
            <h2 className="section-title">Regulated Industry Launch Templates</h2>
            <p className="section-desc">Start from domain workflows that enterprise buyers care about: regulation-to-code, claims governance, release risk, and audit evidence.</p>
            <div className="templates-list">
              {TEMPLATES.map((tpl) => (
                <div 
                  key={tpl.id} 
                  className="template-card" 
                  style={{ "--card-gradient": tpl.gradient }}
                  onClick={() => onSelectTemplate(tpl.prompt)}
                >
                  <div className="template-badge">Template</div>
                  <h3>{tpl.title}</h3>
                  <p>{tpl.description}</p>
                  <button className="template-btn">Launch Pipeline</button>
                </div>
              ))}
            </div>
          </section>

          {/* Workflow Roadmap */}
          <section className="home-section">
            <h2 className="section-title">Governed Delivery Roadmap</h2>
            <p className="section-desc">Each workflow should be governed by policy checks, risk scoring, human approvals, execution, testing, launch, and evidence capture.</p>
            <div className="roadmap-flow">
              <div className="roadmap-step">
                <div className="step-circle">1</div>
                <div className="step-label">Intake</div>
                <div className="step-desc">Request or regulation</div>
              </div>
              <div className="roadmap-connector" />
              <div className="roadmap-step">
                <div className="step-circle">2</div>
                <div className="step-label">Risk</div>
                <div className="step-desc">Controls scored</div>
              </div>
              <div className="roadmap-connector" />
              <div className="roadmap-step">
                <div className="step-circle">3</div>
                <div className="step-label">Approval</div>
                <div className="step-desc">Human gate</div>
              </div>
              <div className="roadmap-connector" />
              <div className="roadmap-step">
                <div className="step-circle">4</div>
                <div className="step-label">Execution</div>
                <div className="step-desc">Agent team works</div>
              </div>
              <div className="roadmap-connector" />
              <div className="roadmap-step">
                <div className="step-circle">5</div>
                <div className="step-label">Validation</div>
                <div className="step-desc">Tests + controls</div>
              </div>
              <div className="roadmap-connector" />
              <div className="roadmap-step">
                <div className="step-circle">6</div>
                <div className="step-label">Evidence</div>
                <div className="step-desc">Audit pack</div>
              </div>
            </div>
          </section>
        </div>

        <div className="home-right">
          {/* Agent Team Showcase */}
          <section className="home-section">
            <h2 className="section-title">Governed Agent Workforce</h2>
            <p className="section-desc">Agents are positioned as digital workers with roles, permissions, controls, KPIs, and audit history.</p>
            <div className="agents-showcase">
              {AGENTS.map((ag) => (
                <div key={ag.name} className="agent-show-card" style={{ borderLeftColor: ag.color }}>
                  <div className="agent-header">
                    <span className="agent-badge" style={{ backgroundColor: ag.color + "1a", color: ag.color }}>
                      {ag.file}
                    </span>
                    <h4>{ag.name}</h4>
                  </div>
                  <p>{ag.role}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Recent Runs feed */}
          <section className="home-section">
            <div className="section-header-row">
              <h2 className="section-title">Recent Build Projects</h2>
              <button className="view-all-btn" onClick={() => onSwitchTab("history")}>
                View All History
              </button>
            </div>
            <p className="section-desc">Quickly monitor status of your last project runs.</p>
            <div className="recent-runs-list">
              {recentRuns.length === 0 ? (
                <div className="recent-empty">No projects built yet. Enter a prompt to start!</div>
              ) : (
                recentRuns.map((r) => (
                  <div 
                    key={r.project_id} 
                    className="recent-run-row"
                    onClick={() => onSwitchTab("history")}
                  >
                    <div className="row-left">
                      <span className={`status-pill ${r.status || "completed"}`}>
                        {r.status || "completed"}
                      </span>
                      <div className="recent-title-group">
                        <span className="recent-id">{r.project_id}</span>
                        <span className="recent-act">{r.activity}</span>
                      </div>
                    </div>
                    <span className="recent-date">
                      {(r.created_at || "").slice(0, 10)}
                    </span>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
