import { useCallback, useEffect, useState } from "react";
import LoanProcessing from "./LoanProcessing.jsx";
import AccountProcessing from "./AccountProcessing.jsx";
import SettingsDialog from "./SettingsDialog.jsx";
import ChatWindow from "./ChatWindow.jsx";
import LedgerRecords from "./LedgerRecords.jsx";
import { record as recordActivity, hasKey } from "../activityLedger.js";
import useInstitutionSettings from "../hooks/useInstitutionSettings.js";
import { useActiveCount } from "../hooks/useLoanJobs.js";
import { ensureConfig } from "../loanJobStore.js";
import "../styles_processing.css";

/**
 * ProcessingWindow — the application's second window.
 *
 * Landing page → Processing → Orchestrator. This window owns the processing
 * suites (Loan and Account) and the live status of everything they are running;
 * the orchestrator is entered from here, and "← Landing page" goes back.
 */
const LS_SECTION = "prefectos_landing_section";

// The ledger is a rail entry like the suites, but it is a record rather than
// a workspace — it lists what this access key has done, not what it can do.
const LEDGER = {
  id: "ledger",
  label: "Ledger Records",
  icon: "▤",
  desc: "Day-wise activity for this access key",
  count: "Audit",
};

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

export default function ProcessingWindow({ onBack, onOpenOrchestrator, currentUser = null }) {
  const [section, setSectionState] = useState(() => {
    try {
      const saved = localStorage.getItem(LS_SECTION);
      return SECTIONS.some((s) => s.id === saved) || saved === LEDGER.id ? saved : "loan";
    } catch {
      return "loan";
    }
  });

  const setSection = useCallback((id) => {
    setSectionState(id);
    try {
      localStorage.setItem(LS_SECTION, id);
    } catch {
      /* storage disabled */
    }
  }, []);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const { bankName, fxRate, policyPath, save } = useInstitutionSettings();

  useEffect(() => {
    ensureConfig("loan");
    ensureConfig("account");
  }, []);

  // The sign-in itself is only visible to the browser, so record it here —
  // once per browser session, when the workspace opens with a key present.
  useEffect(() => {
    if (!hasKey()) return;
    try {
      if (sessionStorage.getItem("prefectos_login_recorded")) return;
      sessionStorage.setItem("prefectos_login_recorded", "1");
    } catch {
      /* storage disabled — the record is simply repeated */
    }
    recordActivity("login", `Signed in to the processing workspace`, {
      institution: currentUser?.institution || null,
      role: currentUser?.role || null,
    });
  }, [currentUser]);

  const runningLoan = useActiveCount("loan");
  const runningAccount = useActiveCount("account");
  const running = { loan: runningLoan, account: runningAccount };
  const runningTotal = runningLoan + runningAccount;

  return (
    <div className="landing-root">
      {/* ── Window header ──────────────────────────────────────────────────── */}
      <header className="lh-bar">
        <div className="lh-brand">
          <button className="pw-back" onClick={onBack} title="Back to the landing page">
            <span aria-hidden="true">←</span> Landing page
          </button>

          <div className="lh-title-group">
            <span className="lh-name">Processing Status</span>
            <span className="lh-subtag">LOAN &amp; ACCOUNT SUITES</span>
          </div>

          {currentUser?.name && (
            <span className="pw-signed-in" title="Signed in — the workspace is licensed per institution">
              {currentUser.name}
              {currentUser.role ? <em> · {currentUser.role}</em> : null}
            </span>
          )}
        </div>

        <div className="lh-right">
          <span className={"pw-live-pill" + (runningTotal > 0 ? " active" : "")}>
            {runningTotal > 0 ? (
              <>
                <i className="ln-live-dot" />
                {runningTotal} job{runningTotal > 1 ? "s" : ""} processing
              </>
            ) : (
              "All queues idle"
            )}
          </span>

          <button
            className="lh-bank-badge"
            onClick={() => setSettingsOpen(true)}
            title="Click to update Institution Settings"
          >
            <div className="lh-bank-badge-left">
              <div className="lh-bank-icon-box">🏦</div>
              <div className="lh-bank-text-group">
                <span className="lh-bank-sublabel">Banking Institution</span>
                <span className="lh-bank-name">{bankName || "Imperial Financial Bank"}</span>
              </div>
            </div>
            <span className="lh-bank-edit-hint">Settings ⚙️</span>
          </button>

          <button
            className="pw-ask"
            onClick={() => setChatOpen(true)}
            title="Ask a question about the bank's own policies — answered from the indexed pack"
          >
            💬 Ask the policy
          </button>

          <button className="pw-orchestrator" onClick={() => onOpenOrchestrator(section)}>
            Open Orchestrator Hub <span aria-hidden="true">→</span>
          </button>
        </div>
      </header>

      <SettingsDialog
        open={settingsOpen}
        bankName={bankName}
        fxRate={fxRate}
        policyPath={policyPath}
        onSave={save}
        onClose={() => setSettingsOpen(false)}
      />

      <ChatWindow
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        policyPath={policyPath}
        bankName={bankName}
      />

      {/* ── Suite rail + the selected suite ────────────────────────────────── */}
      <div className="landing">
        <nav className="landing-nav" aria-label="Processing sections">
          <div className="ln-heading">Processing Suites</div>

          {SECTIONS.map((s) => (
            <button
              key={s.id}
              className={"ln-item" + (section === s.id ? " active" : "")}
              aria-current={section === s.id ? "page" : undefined}
              onClick={() => setSection(s.id)}
            >
              <span className="ln-item-icon">{s.icon}</span>
              <span className="ln-item-body">
                <span className="ln-item-label-row">
                  <span className="ln-item-label">{s.label}</span>
                  {running[s.id] > 0 ? (
                    <span className="ln-item-live" title="Processing continues while you work elsewhere">
                      <i className="ln-live-dot" />
                      {running[s.id]} running
                    </span>
                  ) : (
                    <span className="ln-item-badge">{s.count}</span>
                  )}
                </span>
                <span className="ln-item-desc">{s.desc}</span>
              </span>
            </button>
          ))}

          <button
            className={"ln-item" + (section === LEDGER.id ? " active" : "")}
            aria-current={section === LEDGER.id ? "page" : undefined}
            onClick={() => setSection(LEDGER.id)}
          >
            <span className="ln-item-icon">{LEDGER.icon}</span>
            <span className="ln-item-body">
              <span className="ln-item-label-row">
                <span className="ln-item-label">{LEDGER.label}</span>
                <span className="ln-item-badge">{LEDGER.count}</span>
              </span>
              <span className="ln-item-desc">{LEDGER.desc}</span>
            </span>
          </button>

          <div className="ln-foot">
            <button className="ln-liverun" onClick={() => onOpenOrchestrator(section)}>
              <span>Open Orchestrator Hub</span>
              <span aria-hidden="true">→</span>
            </button>
            <p className="ln-foot-note">
              Build or govern multi-agent workflow pipelines with live telemetry.
            </p>
          </div>
        </nav>

        <main className="landing-body">
          {section === LEDGER.id ? (
            <LedgerRecords />
          ) : section === "loan" ? (
            <LoanProcessing
              onOpenOrchestrator={() => onOpenOrchestrator(section)}
              bankName={bankName}
              fxRate={fxRate}
              policyPath={policyPath}
            />
          ) : (
            <AccountProcessing
              onOpenOrchestrator={() => onOpenOrchestrator(section)}
              bankName={bankName}
              fxRate={fxRate}
              policyPath={policyPath}
            />
          )}
        </main>
      </div>
    </div>
  );
}
