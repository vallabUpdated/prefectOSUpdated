import { useCallback, useEffect, useState } from "react";
import SettingsDialog from "./SettingsDialog.jsx";
import AuthModal from "./AuthModal.jsx";
import EnterpriseSecurityModal from "./EnterpriseSecurityModal.jsx";
import ContactSalesModal from "./ContactSalesModal.jsx";
import ClientSandboxModal from "./ClientSandboxModal.jsx";
import PillarDetailModal from "./PillarDetailModal.jsx";
import RoiCalculator from "./RoiCalculator.jsx";
import { useActiveCount } from "../hooks/useLoanJobs.js";
import { ensureConfig } from "../loanJobStore.js";
import "../styles_suites_door.css";

const LS_BANK = "prefectos_bank_name";
const LS_FX = "prefectos_usd_inr";
const LS_SECTION = "prefectos_landing_section";
const LS_POLICY = "prefectos_policy_pack";
const DEFAULT_FX = 88;

const CLIENT_INSTITUTIONS = [
  "Imperial Financial Bank",
  "Barclays Corporate",
  "Standard Chartered",
  "Citigroup Commercial",
  "Fintech Global Capital",
];

const SECTIONS = [
  {
    id: "loan",
    label: "Loan Processing",
    icon: "◧",
    desc: "Home · Vehicle · Mortgage · Personal",
    count: "4 Products",
  },
  {
    id: "account",
    label: "Account Processing",
    icon: "◍",
    desc: "Statement · KYC · General",
    count: "3 Products",
  },
];

export default function LandingPage({ onOpenOrchestrator, onOpenProcessing, currentUser, onUserUpdate }) {
  const [section, setSectionState] = useState(() => {
    try {
      const saved = localStorage.getItem(LS_SECTION);
      return SECTIONS.some((s) => s.id === saved) ? saved : "loan";
    } catch {
      return "loan";
    }
  });

  const setSection = useCallback((id) => {
    setSectionState(id);
    try {
      localStorage.setItem(LS_SECTION, id);
    } catch {
      /* storage fallback */
    }
  }, []);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authTab, setAuthTab] = useState("login");
  const [securityModalOpen, setSecurityModalOpen] = useState(false);
  const [salesModalOpen, setSalesModalOpen] = useState(false);
  const [sandboxModalOpen, setSandboxModalOpen] = useState(false);
  const [selectedPillar, setSelectedPillar] = useState(null);

  useEffect(() => {
    ensureConfig("loan");
    ensureConfig("account");
  }, []);

  const runningLoan = useActiveCount("loan");
  const runningAccount = useActiveCount("account");
  const running = { loan: runningLoan, account: runningAccount };

  const [bankName, setBankNameState] = useState(() => {
    try {
      return localStorage.getItem(LS_BANK) || "Imperial Financial Bank";
    } catch {
      return "Imperial Financial Bank";
    }
  });

  const [fxRate, setFxRate] = useState(() => {
    try {
      const stored = Number.parseFloat(localStorage.getItem(LS_FX));
      return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_FX;
    } catch {
      return DEFAULT_FX;
    }
  });

  const [policyPath, setPolicyPath] = useState(() => {
    try {
      return localStorage.getItem(LS_POLICY) || "";
    } catch {
      return "";
    }
  });

  const saveSettings = useCallback(({ bankName: name, fxRate: rate, policyPath: pack }) => {
    setBankNameState(name);
    setFxRate(rate);
    setPolicyPath(pack || "");
    try {
      localStorage.setItem(LS_BANK, name);
      localStorage.setItem(LS_FX, String(rate));
      localStorage.setItem(LS_POLICY, pack || "");
    } catch {
      /* storage fallback */
    }
  }, []);

  const handleInstitutionSelect = (e) => {
    const selected = e.target.value;
    setBankNameState(selected);
    try {
      localStorage.setItem(LS_BANK, selected);
    } catch {
      /* storage fallback */
    }
  };

  const openAuth = (tab) => {
    setAuthTab(tab);
    setAuthModalOpen(true);
  };

  // The processing suites are a licensed workspace: a page of their own, and
  // only for a signed-in licensee. A guest asking for them gets the sign-in
  // dialog, and lands in the workspace once the key checks out.
  const signedIn = !!(currentUser && currentUser.id && currentUser.id !== "local");
  const [pendingSuites, setPendingSuites] = useState(false);

  const openSuites = (id = null) => {
    if (id) setSection(id);
    if (!signedIn) {
      setPendingSuites(true);
      openAuth("login");
      return;
    }
    if (onOpenProcessing) onOpenProcessing();
  };

  const handleAuthenticated = (userObj) => {
    if (onUserUpdate) onUserUpdate(userObj);
    if (userObj.institution) setBankNameState(userObj.institution);
    if (pendingSuites) {
      setPendingSuites(false);
      if (onOpenProcessing) onOpenProcessing();
    }
  };

  const handleLogout = () => {
    try {
      localStorage.removeItem("prefectos_user_id");
      localStorage.removeItem("prefectos_user_name");
      localStorage.removeItem("prefectos_user_email");
      localStorage.removeItem("prefectos_user_role");
    } catch {
      /* storage fallback */
    }
    if (onUserUpdate) onUserUpdate({ id: "local", name: "Guest User", role: "approver" });
  };

  const scrollToSection = (id) => {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth" });
  };

  const handleLaunchSandboxDemo = (prompt) => {
    if (onOpenOrchestrator) {
      onOpenOrchestrator(prompt);
    }
  };

  return (
    <div className="landing-root dark-theme">
      {/* ── LIVE HOSTING STATUS BAR ────────────────────────────────────────── */}
      <div className="dark-status-bar">
        <div className="dark-status-left">
          <span className="status-live-dot" />
          <span>LIVE HOSTING STATUS: <strong>OPERATIONAL (99.99% UPTIME SLA)</strong></span>
          <span className="status-sep">|</span>
          <button className="status-link-btn" onClick={() => setSecurityModalOpen(true)}>
            🛡️ SOC2 Type II Certified
          </button>
        </div>
        <div className="dark-status-right">
          <span>Enterprise Cloud Region: <strong>US-East (AWS Private VPC)</strong></span>
          <button className="status-sales-btn" onClick={() => setSalesModalOpen(true)}>
            Contact Sales / SLA Quote →
          </button>
        </div>
      </div>

      {/* ── TOP HEADER BAR ─────────────────────────────────────────────────── */}
      <header className="dark-lh-bar">
        <div className="lh-brand">
          <img
            src="/prefectos-logo.png"
            alt="Prefect OS"
            className="dark-lh-logo-img"
            onClick={() => onOpenOrchestrator && onOpenOrchestrator()}
          />
          <span className="dark-lh-name" onClick={() => onOpenOrchestrator && onOpenOrchestrator()}>
            Prefect OS
          </span>

          <nav className="dark-lh-nav">
            <button onClick={() => scrollToSection("telemetry-card")}>Monitoring</button>
            <button onClick={() => scrollToSection("governance-section")}>Governance</button>
            <button onClick={() => scrollToSection("roi-calculator")}>ROI Savings</button>
            <button onClick={() => scrollToSection("suites-section")}>Suites</button>
          </nav>
        </div>

        <div className="lh-right">
          <div className="dark-lh-tenant-select" title="Switch Client Enterprise Environment">
            <span className="tenant-icon">🏦</span>
            <select value={bankName} onChange={handleInstitutionSelect}>
              {CLIENT_INSTITUTIONS.map((inst) => (
                <option key={inst} value={inst}>
                  {inst}
                </option>
              ))}
            </select>
          </div>

          <button
            className="dark-lh-bank-badge"
            onClick={() => setSettingsOpen(true)}
            title="Click to update Institution Settings"
          >
            <span className="dark-lh-bank-gear">⚙️</span>
          </button>

          {currentUser && currentUser.id && currentUser.id !== "local" ? (
            <div className="dark-user-chip">
              <div className="dark-user-avatar">{currentUser.name.charAt(0).toUpperCase()}</div>
              <div className="dark-user-info">
                <span className="dark-user-name">{currentUser.name}</span>
                <span className="dark-user-role">{currentUser.role || "Approver"}</span>
              </div>
              <button className="dark-logout-btn" onClick={handleLogout} title="Log Out">
                🚪
              </button>
            </div>
          ) : (
            <div className="dark-auth-group">
              <button className="dark-btn-login" onClick={() => openAuth("login")}>
                🔑 Log In
              </button>
            </div>
          )}
        </div>
      </header>

      {/* MODALS */}
      <SettingsDialog
        open={settingsOpen}
        bankName={bankName}
        fxRate={fxRate}
        policyPath={policyPath}
        onSave={saveSettings}
        onClose={() => setSettingsOpen(false)}
      />

      <AuthModal
        open={authModalOpen}
        initialTab={authTab}
        onClose={() => setAuthModalOpen(false)}
        onAuthenticate={handleAuthenticated}
      />

      <EnterpriseSecurityModal
        open={securityModalOpen}
        onClose={() => setSecurityModalOpen(false)}
      />

      <ContactSalesModal
        open={salesModalOpen}
        onClose={() => setSalesModalOpen(false)}
      />

      <ClientSandboxModal
        open={sandboxModalOpen}
        onClose={() => setSandboxModalOpen(false)}
        onLaunchDemo={handleLaunchSandboxDemo}
      />

      <PillarDetailModal
        open={Boolean(selectedPillar)}
        pillarKey={selectedPillar}
        onClose={() => setSelectedPillar(null)}
      />

      {/* ── SCROLLABLE BODY ────────────────────────────────────────────────── */}
      <div className="dark-landing-scroll">
        {/* HERO HEADER */}
        <section className="dark-hero-section">
          <div className="client-badge">
            <span>ENTERPRISE HOSTING READY · SOC2 TYPE II &amp; ISO 27001 VERIFIED</span>
          </div>

          <h1 className="dark-hero-title">
            Deterministic Multi-Agent Orchestration <br />
            &amp; Enterprise Governance
          </h1>
          <p className="dark-hero-subtitle">
            Streamlining complex workflows with precise control and comprehensive compliance.
          </p>

          <div className="hero-action-buttons">
            <button className="hero-btn-primary" onClick={() => setSandboxModalOpen(true)}>
              🚀 Launch Client Sandbox Demo →
            </button>
            <button className="hero-btn-secondary" onClick={() => setSecurityModalOpen(true)}>
              🛡️ View Security &amp; Compliance SLA
            </button>
            <button className="hero-btn-accent" onClick={() => setSalesModalOpen(true)}>
              🏢 Request Enterprise Quote
            </button>
          </div>

          {/* MAIN APPROVED TELEMETRY DASHBOARD CARD (EXACT MOCKUP IMPLEMENTATION) */}
          <div id="telemetry-card" className="mockup-dashboard-card glowing-card ultra-beautiful">
            {/* CARD FRAME CONTROL HEADER */}
            <div className="card-top-control-bar">
              <div className="ct-left">
                <span className="ct-dot" />
                <span className="ct-title">LIVE MULTI-AGENT TOPOLOGY TELEMETRY · RUN ID: prf_run_9941a</span>
              </div>
              <div className="ct-right">
                <button className="ct-action-icon-btn" title="Refresh Telemetry">🔄</button>
                <button className="ct-action-icon-btn" title="More Options">•••</button>
              </div>
            </div>

            {/* TOP MAIN ROW: AGENT TOPOLOGY GRAPH + RECENT AGENT ACTIONS PANEL */}
            <div className="telemetry-main-row">
              {/* 3D EYE-CATCHING AGENT TOPOLOGY GRAPH WITH LIVE DATA FLOW OVERLAY */}
              <div className="mockup-topology-container neon-border glass-container-3d relative-container">
                <img
                  src="/prefectos_eye_catching_topology_diagram.jpg"
                  alt="3D Multi-Agent Workflow Topology Diagram"
                  className="topology-3d-image"
                />

                {/* LIVE ANIMATED DATA FLOW OVERLAY */}
                <div className="live-flow-overlay">
                  <svg width="100%" height="100%" viewBox="0 0 1000 562" preserveAspectRatio="xMidYMid slice" fill="none">
                    <defs>
                      <filter id="liveGlowCyan" x="-20%" y="-20%" width="140%" height="140%">
                        <feGaussianBlur stdDeviation="6" result="blur" />
                        <feComposite in="SourceGraphic" in2="blur" operator="over" />
                      </filter>
                      <filter id="liveGlowIndigo" x="-20%" y="-20%" width="140%" height="140%">
                        <feGaussianBlur stdDeviation="6" result="blur" />
                        <feComposite in="SourceGraphic" in2="blur" operator="over" />
                      </filter>
                      <linearGradient id="liveFlowGrad" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#00f2ff" />
                        <stop offset="35%" stopColor="#38bdf8" />
                        <stop offset="70%" stopColor="#818cf8" />
                        <stop offset="100%" stopColor="#10b981" />
                      </linearGradient>
                    </defs>

                    {/* Primary Flow Conduits */}
                    <path d="M 100 280 L 220 280 L 380 280" stroke="url(#liveFlowGrad)" strokeWidth="4.5" strokeDasharray="12 12" className="live-dash-pulse" filter="url(#liveGlowCyan)" />
                    <path d="M 380 280 Q 480 180 540 180" stroke="#38bdf8" strokeWidth="4" strokeDasharray="10 10" className="live-dash-pulse" filter="url(#liveGlowCyan)" />
                    <path d="M 380 280 Q 480 380 540 380" stroke="#38bdf8" strokeWidth="4" strokeDasharray="10 10" className="live-dash-pulse" filter="url(#liveGlowCyan)" />

                    <path d="M 540 180 Q 640 230 730 230" stroke="#818cf8" strokeWidth="4" strokeDasharray="10 10" className="live-dash-pulse" filter="url(#liveGlowIndigo)" />
                    <path d="M 540 380 Q 640 330 730 330" stroke="#818cf8" strokeWidth="4" strokeDasharray="10 10" className="live-dash-pulse" filter="url(#liveGlowIndigo)" />

                    <path d="M 730 280 L 890 280" stroke="#10b981" strokeWidth="4.5" strokeDasharray="12 12" className="live-dash-pulse" />

                    {/* Multiple Live Data Packets / Energy Particles */}
                    <circle r="7" fill="#00f2ff" filter="url(#liveGlowCyan)">
                      <animateMotion dur="1.8s" repeatCount="indefinite" path="M 100 280 L 220 280 L 380 280" />
                    </circle>
                    <circle r="4" fill="#ffffff">
                      <animateMotion dur="1.8s" begin="0.9s" repeatCount="indefinite" path="M 100 280 L 220 280 L 380 280" />
                    </circle>

                    <circle r="6" fill="#38bdf8" filter="url(#liveGlowCyan)">
                      <animateMotion dur="1.5s" repeatCount="indefinite" path="M 380 280 Q 480 180 540 180 Q 640 230 730 230" />
                    </circle>
                    <circle r="4" fill="#ffffff">
                      <animateMotion dur="1.5s" begin="0.75s" repeatCount="indefinite" path="M 380 280 Q 480 180 540 180 Q 640 230 730 230" />
                    </circle>

                    <circle r="6" fill="#818cf8" filter="url(#liveGlowIndigo)">
                      <animateMotion dur="1.6s" repeatCount="indefinite" path="M 380 280 Q 480 380 540 380 Q 640 330 730 330" />
                    </circle>

                    <circle r="7" fill="#10b981" filter="url(#liveGlowCyan)">
                      <animateMotion dur="1.4s" repeatCount="indefinite" path="M 730 280 L 890 280" />
                    </circle>
                    <circle r="4" fill="#ffffff">
                      <animateMotion dur="1.4s" begin="0.7s" repeatCount="indefinite" path="M 730 280 L 890 280" />
                    </circle>

                    {/* Live Pulsing Node Status Rings */}
                    <circle cx="100" cy="280" r="30" fill="none" stroke="#00f2ff" strokeWidth="2.5" className="live-ping-ring" />
                    <circle cx="220" cy="280" r="28" fill="none" stroke="#38bdf8" strokeWidth="2.5" className="live-ping-ring-delay" />
                    <polygon points="380,246 414,280 380,314 346,280" fill="none" stroke="#00f2ff" strokeWidth="2.5" className="live-ping-ring" />
                    <circle cx="730" cy="280" r="36" fill="none" stroke="#818cf8" strokeWidth="2.5" className="live-ping-ring" />
                    <circle cx="890" cy="280" r="32" fill="none" stroke="#10b981" strokeWidth="3" className="live-ping-ring-delay" />
                  </svg>

                  {/* Live Stream Telemetry Badges */}
                  <div className="live-data-badge badge-top-left">
                    <span className="live-pulse-dot green" />
                    <span>LIVE STREAM: 1,420 pkts/s</span>
                  </div>
                  <div className="live-data-badge badge-top-mid">
                    <span className="live-pulse-dot cyan" />
                    <span>LATENCY: 1.20ms</span>
                  </div>
                  <div className="live-data-badge badge-gate">
                    <span className="live-pulse-dot blue" />
                    <span>HITL GATE PASSED ✓</span>
                  </div>
                  <div className="live-data-badge badge-swarm">
                    <span className="live-pulse-dot purple" />
                    <span>SWARM: 4 WORKERS</span>
                  </div>
                  <div className="live-data-badge badge-ledger">
                    <span className="live-pulse-dot emerald" />
                    <span>SHA-256 SIGNED 🔒</span>
                  </div>
                </div>
              </div>

              {/* RECENT AGENT ACTIONS FEED PANEL */}
              <div className="mockup-actions-card glass-card">
                <div className="mockup-card-title">
                  <span>Recent agent actions</span>
                  <span className="mockup-dots">⋮</span>
                </div>
                <div className="mockup-actions-list">
                  <div className="action-row-item">
                    <span className="action-time-badge cyan">7:39 PM</span>
                    <span className="action-status-pill">Status</span>
                    <span className="action-status-pill cyan">Status</span>
                    <div className="action-name-text">Execute agent topology</div>
                  </div>

                  <div className="action-row-item">
                    <span className="action-time-badge blue">8:53 PM</span>
                    <span className="action-status-pill">Status</span>
                    <span className="action-status-pill blue">Status</span>
                    <div className="action-name-text">Agent action stream</div>
                  </div>

                  <div className="action-row-item">
                    <span className="action-time-badge blue">8:47 PM</span>
                    <span className="action-status-pill">Status</span>
                    <div className="action-name-text">Agent actions stream</div>
                  </div>

                  <div className="action-row-item">
                    <span className="action-time-badge green">8:59 PM</span>
                    <span className="action-status-pill green">Completed</span>
                    <span className="action-status-pill">Status</span>
                  </div>
                </div>
              </div>
            </div>

            {/* METRICS & TELEMETRY GRID WITH GLASSMORPHISM & NEON ACCENTS */}
            <div className="mockup-metrics-grid horizontal-layout">
              {/* Token Budget Usage Arc Gauge */}
              <div className="mockup-gauge-card glass-card">
                <div className="mockup-card-title">
                  <span>Token budget</span>
                </div>
                <div className="mockup-arc-wrapper">
                  <svg width="190" height="105" viewBox="0 0 200 110">
                    <path
                      d="M 20 100 A 80 80 0 0 1 180 100"
                      fill="none"
                      stroke="rgba(255, 255, 255, 0.08)"
                      strokeWidth="16"
                      strokeLinecap="round"
                    />
                    <path
                      d="M 20 100 A 80 80 0 0 1 155 45"
                      fill="none"
                      stroke="url(#gaugeGrad)"
                      strokeWidth="16"
                      strokeLinecap="round"
                      filter="url(#glowCyanHigh)"
                    />
                    <defs>
                      <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
                        <stop offset="0%" stopColor="#00f2ff" />
                        <stop offset="50%" stopColor="#38bdf8" />
                        <stop offset="100%" stopColor="#34d399" />
                      </linearGradient>
                    </defs>
                  </svg>
                  <div className="mockup-gauge-val glowing-text">78%</div>
                </div>
              </div>

              {/* Active Agents */}
              <div className="mockup-stat-box glass-card">
                <div className="mockup-stat-label">Active Agents</div>
                <div className="mockup-stat-num">24/32</div>
                <div className="stat-progress-bar">
                  <div className="stat-progress-fill cyan" style={{ width: "75%" }} />
                </div>
              </div>

              {/* Running Processes */}
              <div className="mockup-stat-box glass-card">
                <div className="mockup-stat-label">Running Processes</div>
                <div className="mockup-stat-num">15</div>
                <div className="mini-wave-chart">
                  <svg width="100%" height="32" viewBox="0 0 120 32" fill="none">
                    <path d="M 0 24 Q 20 5 40 20 T 80 10 T 120 18" stroke="#00f2ff" strokeWidth="2.5" fill="none" />
                  </svg>
                </div>
              </div>

              {/* Completed Tasks */}
              <div className="mockup-stat-box glass-card">
                <div className="mockup-stat-label">Completed Tasks</div>
                <div className="mockup-stat-num green">
                  1.2k <span className="mockup-check-circle">✓</span>
                </div>
              </div>

              {/* Error Rate */}
              <div className="mockup-stat-box glass-card">
                <div className="mockup-stat-label">Error Rate</div>
                <div className="mockup-stat-num">0.1%</div>
              </div>

              {/* Error Rate Secondary Info */}
              <div className="mockup-stat-box glass-card sub-info-card">
                <div className="mockup-stat-label">Error Rate</div>
                <div className="mockup-stat-num large">0.1%</div>
                <div className="mockup-stat-sub-text">Newer agent actions using tracked currents.</div>
              </div>
            </div>

            {/* 6 PILL FEATURE BAR (3D GLOWING GLASS SWITCHES) */}
            <div className="features-section-wrapper">
              <div className="features-label">Features</div>
              <div id="features-grid" className="mockup-feature-pills">
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("budget")}>
                  <div className="mockup-pill-icon cyan-glow">⏲</div>
                  <span>Budget Cap Control</span>
                </div>
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("hitl")}>
                  <div className="mockup-pill-icon blue-glow">👤</div>
                  <span>Human-in-the-loop Approval Gates</span>
                </div>
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("ledger")}>
                  <div className="mockup-pill-icon indigo-glow">📄</div>
                  <span>Immutable Audit Ledger</span>
                </div>
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("governance")}>
                  <div className="mockup-pill-icon emerald-glow">🧠</div>
                  <span>Model Governance</span>
                </div>
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("execution")}>
                  <div className="mockup-pill-icon cyan-glow">⬟</div>
                  <span>Parallel Execution</span>
                </div>
                <div className="mockup-pill-item interactive pill-3d" onClick={() => setSelectedPillar("monitoring")}>
                  <div className="mockup-pill-icon emerald-glow">📈</div>
                  <span>Deployment Monitoring</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ── DEDICATED SEPARATE GOVERNANCE SECTION ──────────────────────────── */}
        <section id="governance-section" className="dark-suites-container governance-section">
          <div className="governance-card">
            <div className="gov-header">
              <span className="section-kicker">ENTERPRISE GOVERNANCE ENGINE</span>
              <h2>Deterministic Multi-Agent Risk &amp; Compliance Governance</h2>
              <p>
                Prefect OS wraps autonomous LLM agent execution in strict, non-bypassable governance bounds designed specifically for enterprise banking and financial risk teams.
              </p>
            </div>

            <div className="gov-grid">
              <div className="gov-feature-box">
                <div className="gov-icon">🔒</div>
                <h3>Hard Budget Cap Counter</h3>
                <p>
                  Hard capped at <strong>MAX_AGENTS = 10</strong> per run. Automatic <code>BudgetExhaustedError</code> enforcement prevents runaway LLM loops and infinite API token spend.
                </p>
                <div className="gov-badge-pill">Module-Level Cap: 10 Active Agents</div>
              </div>

              <div className="gov-feature-box">
                <div className="gov-icon">✋</div>
                <h3>Human-In-The-Loop (HITL) Gates</h3>
                <p>
                  Every stage suspends execution with <code>interrupt()</code>. Human decision makers review agent system prompts, specifications, and code diffs before any write operation.
                </p>
                <div className="gov-badge-pill">Interactive Diff &amp; Edit Engine</div>
              </div>

              <div className="gov-feature-box">
                <div className="gov-icon">📓</div>
                <h3>Cryptographic Decision Ledger</h3>
                <p>
                  Immutable SHA-256 hash chains log every prompt input, state delta, approver signature, and timestamp for zero-trust compliance audits.
                </p>
                <div className="gov-badge-pill">Tamper-Evident Hash Chain</div>
              </div>

              <div className="gov-feature-box">
                <div className="gov-icon">🔄</div>
                <h3>Resilient Checkpoint Resume</h3>
                <p>
                  State graph checkpointing powered by <code>MemorySaver</code>. One-click resume restores exact pipeline execution state after rejection or system crashes.
                </p>
                <div className="gov-badge-pill">LangGraph Checkpoint Recovery</div>
              </div>

              <div className="gov-feature-box">
                <div className="gov-icon">🏦</div>
                <h3>Automated Policy Rulebook Engine</h3>
                <p>
                  Real-time matching against credit policy packs (Fannie Mae underwriting guidelines, KYC/AML rules, and regulatory circular obligations).
                </p>
                <div className="gov-badge-pill">Policy Pack Vector Indexing</div>
              </div>

              <div className="gov-feature-box">
                <div className="gov-icon">🔐</div>
                <h3>Enterprise Role-Based Access (RBAC)</h3>
                <p>
                  Enforces multi-role governance: Underwriters, Risk Officers, Compliance Managers, and Internal Auditors with Okta SAML &amp; Google SSO.
                </p>
                <div className="gov-badge-pill">Role-Based Access Control</div>
              </div>
            </div>
          </div>
        </section>

        {/* ENTERPRISE ROI & SAVINGS CALCULATOR SECTION */}
        <section id="roi-calculator" className="dark-suites-container">
          <RoiCalculator />
        </section>

        {/* PROCESSING SUITES WORKSPACE CONTAINER */}
        <section id="suites-section" className="dark-suites-container">
          <div className="dark-suites-header">
            <h2>Select Enterprise Processing Workspace</h2>
            <p>Access specialized underwriting, statement parsing, and regulatory pipelines.</p>
          </div>

          {/* The workspace itself is a page of its own (ProcessingWindow), and
              it opens only for a signed-in licensee. What lives here is the
              door to it. */}
          <div className="suites-door">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                className={"suite-door-card" + (signedIn ? "" : " locked")}
                onClick={() => openSuites(s.id)}
                title={signedIn ? `Open ${s.label}` : "Sign in to open this workspace"}
              >
                <span className="sdc-icon">{signedIn ? s.icon : "🔒"}</span>
                <span className="sdc-label">{s.label}</span>
                <span className="sdc-desc">{s.desc}</span>
                {signedIn && running[s.id] > 0 ? (
                  <span className="sdc-live">
                    <i className="ln-live-dot" />
                    {running[s.id]} running
                  </span>
                ) : (
                  <span className="sdc-badge">{signedIn ? s.count : "Sign in to access"}</span>
                )}
              </button>
            ))}
          </div>

          <div className="suites-door-cta">
            <button className="hero-btn-primary" onClick={() => openSuites()}>
              <span>{signedIn ? "Open Processing Workspace" : "Sign in to open the workspace"}</span>
              <span className="hero-btn-arrow">→</span>
            </button>
            {!signedIn && (
              <p className="suites-door-note">
                Processing suites are licensed per institution. Sign in with your
                admin-issued access key to open the workspace.
              </p>
            )}
          </div>
        </section>

        {/* FOOTER */}
        <footer className="dark-footer">
          <div className="dark-footer-inner">
            <div className="dark-footer-brand">
              <img src="/prefectos-logo.png" alt="Logo" style={{ width: 22, height: 22, borderRadius: 4 }} />
              <span>Prefect OS Enterprise Orchestrator v2.8</span>
            </div>
            <div className="dark-footer-meta">
              <span>Determinism Guardrails</span> · <span>LangGraph Engine</span> · <span>SOC2 Type II</span> · <span>AWS / Azure / On-Prem VPC</span>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
