import { useEffect, useRef, useState } from "react";
import FolderPicker from "./FolderPicker.jsx";
import { inr, usd, rateLabel } from "../money.js";

/**
 * LoanCard — one loan product box on the Loan Processing page.
 *
 * Holds everything an operator needs for one run: where the documents are,
 * where the results go, the prompt that drives extraction + the eligibility
 * check (editable), and — once running — live progress and token spend
 * streamed from the server.
 */

const ACTIVE = ["starting", "running"];

const STATUS_TEXT = {
  idle: "Ready",
  starting: "Starting…",
  running: "Processing",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

// Loans answer ELIGIBLE / NOT_ELIGIBLE; account work answers COMPLETE /
// INCOMPLETE / REPORTED. Both land in box.decision.
const DECISION_CLASS = {
  ELIGIBLE: "ok",
  NOT_ELIGIBLE: "bad",
  NEEDS_REVIEW: "warn",
  COMPLETE: "ok",
  INCOMPLETE: "bad",
  REPORTED: "info",
};

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

const THEME_CLASS = {
  home: "theme-home",
  vehicle: "theme-vehicle",
  mortgage: "theme-mortgage",
  personal: "theme-personal",
  statement: "theme-statement",
  account_statement: "theme-statement",
  kyc: "theme-kyc",
  general: "theme-general",
};

const statementSvg = (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <polyline points="10 9 9 9 8 9" />
  </svg>
);

const PRODUCT_ICONS = {
  home: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <polyline points="9 22 9 12 15 12 15 22" />
    </svg>
  ),
  vehicle: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2" />
      <circle cx="7" cy="17" r="2" />
      <path d="M9 17h6" />
      <circle cx="17" cy="17" r="2" />
    </svg>
  ),
  mortgage: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2" ry="2" />
      <path d="M9 22v-4h6v4" />
      <line x1="8" y1="6" x2="8.01" y2="6" />
      <line x1="16" y1="6" x2="16.01" y2="6" />
      <line x1="8" y1="10" x2="8.01" y2="10" />
      <line x1="16" y1="10" x2="16.01" y2="10" />
      <line x1="8" y1="14" x2="8.01" y2="14" />
      <line x1="16" y1="14" x2="16.01" y2="14" />
    </svg>
  ),
  personal: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <line x1="2" y1="10" x2="22" y2="10" />
    </svg>
  ),
  statement: statementSvg,
  account_statement: statementSvg,
  kyc: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  ),
  general: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
      <line x1="12" y1="11" x2="12" y2="17" />
      <line x1="9" y1="14" x2="15" y2="14" />
    </svg>
  ),
};

export default function LoanCard({ box, actions, fxRate, policyPath = "" }) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [picking, setPicking] = useState(null); // "input" | "output" | null
  const scanTimer = useRef(null);

  const active = ACTIVE.includes(box.status);
  const pct = box.total ? Math.round((box.done / box.total) * 100) : 0;
  const tokensTotal = box.tokensIn + box.tokensOut;
  const themeClass = THEME_CLASS[box.loanType] || "theme-general";
  const icon = PRODUCT_ICONS[box.loanType] || (typeof box.icon === "object" ? box.icon : null) || "📄";

  // The server reports elapsed time with each event; between events the card
  // keeps counting locally so the clock doesn't freeze mid-document.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  const elapsed = active && box.elapsedAt
    ? box.elapsedS + (now - box.elapsedAt) / 1000
    : box.elapsedS;

  // Debounced document count for the typed input path
  useEffect(() => {
    if (scanTimer.current) clearTimeout(scanTimer.current);
    if (!box.inputPath.trim()) return undefined;
    scanTimer.current = setTimeout(() => actions.scanInput(box.loanType, box.inputPath), 600);
    return () => clearInterval(scanTimer.current);
  }, [box.inputPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const canStart = box.inputPath.trim() && box.outputPath.trim() && !active;

  const progressLabel = () => {
    if (box.phase === "extracting") return `Parsing and reconciling ${box.currentDoc || "documents"}…`;
    if (box.phase === "exceptions") return "Processing Agent is resolving the failed rows…";
    if (box.phase === "planning") return "Planning Agent is building the processing plan…";
    if (box.phase === "assessment") return "Processing Agent is checking eligibility…";
    if (box.currentDoc) return `Reading ${box.currentDoc}`;
    if (active) return "Scanning documents…";
    if (box.status === "completed") {
      return `${box.done - box.failed} of ${box.total} documents processed`
        + (box.failed ? ` · ${box.failed} unreadable` : "");
    }
    if (box.scan) return `${box.scan.count} document${box.scan.count === 1 ? "" : "s"} found at the input path`;
    return "No run yet";
  };

  const handleUsePreset = () => {
    const sampleInput = `./data/sample_documents/${box.loanType}`;
    const sampleOutput = `./data/output_reports/${box.loanType}`;
    actions.setField(box.loanType, "inputPath", sampleInput);
    actions.setField(box.loanType, "outputPath", sampleOutput);
  };

  return (
    <section className={`loan-card ${themeClass}${active ? " is-active" : ""}`}>
      <header className="lc-head">
        <div className="lc-icon">{icon}</div>
        <h3 className="lc-title">{box.label}</h3>
        {box.reattached && (
          <span className="lc-reattached" title="This run was already going — the page reconnected to it">
            reconnected
          </span>
        )}
        <span className={"lc-status lc-status-" + box.status}>
          {STATUS_TEXT[box.status] || box.status}
        </span>
      </header>

      <div className="lc-field">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <label htmlFor={`in-${box.loanType}`}>Input path — documents to process</label>
          {!active && (
            <button type="button" className="lc-preset-btn" onClick={handleUsePreset}>
              + Sample Preset
            </button>
          )}
        </div>
        <div className="lc-path">
          <input
            id={`in-${box.loanType}`}
            className="lc-input"
            value={box.inputPath}
            disabled={active}
            placeholder="Browse… or paste a folder path"
            onChange={(e) => actions.setField(box.loanType, "inputPath", e.target.value)}
          />
          <button type="button" className="lc-browse" disabled={active}
                  onClick={() => setPicking("input")}>
            📂 Browse…
          </button>
        </div>
        {box.scan && (
          <div className="lc-hint">
            {box.scan.count} processable document{box.scan.count === 1 ? "" : "s"}
            {box.scan.skipped ? ` · ${box.scan.skipped} skipped (unsupported type)` : ""}
          </div>
        )}
      </div>

      <div className="lc-field">
        <label htmlFor={`out-${box.loanType}`}>Output path — reports are written here</label>
        <div className="lc-path">
          <input
            id={`out-${box.loanType}`}
            className="lc-input"
            value={box.outputPath}
            disabled={active}
            placeholder="Browse… or paste a folder path"
            onChange={(e) => actions.setField(box.loanType, "outputPath", e.target.value)}
          />
          <button type="button" className="lc-browse" disabled={active}
                  onClick={() => setPicking("output")}>
            📂 Browse…
          </button>
        </div>
      </div>

      <FolderPicker
        open={picking !== null}
        mode={picking || "input"}
        startPath={picking === "output" ? box.outputPath : box.inputPath}
        onClose={() => setPicking(null)}
        onPick={(path) =>
          actions.setField(box.loanType,
                           picking === "output" ? "outputPath" : "inputPath", path)}
      />

      <div className="lc-field">
        <label>Processing mode</label>
        <div className="lc-mode">
          {[
            ["deterministic", "⚡ Parse first", "Reconcile in code; only failures go to the model", "mode-deterministic"],
            ["ai_first", "🤖 AI for everything", "Send every document to the model", "mode-ai"],
          ].map(([id, label, hint, modeClass]) => (
            <button
              key={id}
              type="button"
              title={hint}
              disabled={active}
              className={"lc-mode-btn" + (box.mode === id ? ` on ${modeClass}` : "")}
              onClick={() => actions.setField(box.loanType, "mode", id)}
            >
              {label}
            </button>
          ))}
          {box.aiShare != null && (
            <span className="lc-mode-share">
              {Math.round(box.aiShare * 100)}% AI
              {box.docsClean ? ` · ${box.docsClean} in code` : ""}
            </span>
          )}
        </div>
      </div>

      {/* Credit policy retrieval — only offered once a pack is configured in
          Settings, so the control never appears without something behind it. */}
      {policyPath && (
        <div className="lc-field">
          <label className="lc-policy-row">
            <input
              type="checkbox"
              checked={!!box.usePolicy}
              disabled={active}
              onChange={(e) => actions.setField(box.loanType, "usePolicy", e.target.checked)}
            />
            <span className="lc-policy-text">
              <b>Cite policy</b> — retrieve the governing clauses from the credit
              policy pack and require the assessment to cite them
            </span>
          </label>
          {box.policyCitations?.length > 0 && (
            <div className="lc-policy-cites">
              {box.policyCitations.length} clause
              {box.policyCitations.length === 1 ? "" : "s"} applied:{" "}
              {box.policyCitations.map((c) => (
                <code key={c.chunk_sha256} title={c.preview}>
                  {c.source} {c.span}
                </code>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="lc-field">
        <div className="lc-prompt-head">
          <button
            type="button"
            className="lc-disclosure"
            aria-expanded={showPrompt}
            onClick={() => setShowPrompt((v) => !v)}
          >
            <span className="lc-caret">{showPrompt ? "▾" : "▸"}</span>
            Processing prompt
            {box.promptEdited && <span className="lc-edited">edited</span>}
          </button>
          {showPrompt && box.promptEdited && (
            <button type="button" className="lc-reset" onClick={() => actions.resetPrompt(box.loanType)}>
              Reset to default
            </button>
          )}
        </div>
        {showPrompt ? (
          <textarea
            className="lc-prompt"
            rows={12}
            value={box.prompt}
            disabled={active}
            onChange={(e) => actions.setField(box.loanType, "prompt", e.target.value)}
          />
        ) : (
          <p className="lc-prompt-preview">{box.prompt.split("\n")[0]}</p>
        )}
      </div>

      <div className="lc-progress-block">
        <div className="lc-progress-row">
          <span className="lc-progress-label">{progressLabel()}</span>
          <span className="lc-progress-pct">
            {box.total ? `${box.done}/${box.total}` : "—"}
          </span>
        </div>
        <div
          className="lc-bar"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${box.label} document processing`}
        >
          <div
            className={
              "lc-bar-fill"
              + (box.status === "failed" ? " bad" : "")
              + (box.phase === "eligibility" ? " pulse" : "")
            }
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {box.agents.length > 0 && (
        <div className="lc-agents">
          {box.agents.map((ag) => (
            <div key={ag.agent_id} className={"lc-agent lc-agent-" + ag.status} title={ag.card}>
              <span className="lc-agent-dot" />
              <span className="lc-agent-name">{ag.label}</span>
              <span className="lc-agent-meta">
                {ag.calls} call{ag.calls === 1 ? "" : "s"} ·{" "}
                {(ag.tokens_in + ag.tokens_out).toLocaleString()} tok
              </span>
            </div>
          ))}
          <span className="lc-agent-cap">{box.agents.length}/2 agents</span>
        </div>
      )}

      <div className="lc-meters">
        <div className="lc-meter meter-tokens">
          <div className="lc-meter-head">
            <span className="lc-meter-icon">⚡</span>
            <span className="lc-meter-label">Tokens</span>
          </div>
          <span className="lc-meter-value">{tokensTotal.toLocaleString()}</span>
          <span className="lc-meter-sub">
            <span className="lc-sub-pill">{box.tokensIn.toLocaleString()} in</span>
            <span className="lc-sub-sep">·</span>
            <span className="lc-sub-pill">{box.tokensOut.toLocaleString()} out</span>
          </span>
        </div>

        <div className="lc-meter meter-cost">
          <div className="lc-meter-head">
            <span className="lc-meter-icon">💳</span>
            <span className="lc-meter-label">Cost</span>
          </div>
          <span className="lc-meter-value strong">{inr(box.costUsd, fxRate)}</span>
          <span className="lc-meter-sub" title={`Billed in USD; converted ${rateLabel(fxRate)}`}>
            <span className="lc-sub-tag">{usd(box.costUsd)}</span>
            <span className="lc-sub-rate">{rateLabel(fxRate)}</span>
          </span>
        </div>

        <div className="lc-meter meter-time">
          <div className="lc-meter-head">
            <span className="lc-meter-icon">⏱️</span>
            <span className="lc-meter-label">Time</span>
          </div>
          <span className={"lc-meter-value" + (active ? " ticking" : "")}>
            {fmtDuration(elapsed)}
          </span>
          <span className="lc-meter-sub">
            <span className="lc-sub-tag">
              {box.done > 0 ? `${fmtDuration(elapsed / box.done)} / doc` : "elapsed"}
            </span>
          </span>
        </div>
      </div>

      {box.runFolder && (
        <div className="lc-runfolder" title={box.runDir}>
          Saved to <code>{box.runFolder}</code>
        </div>
      )}
      {box.decision && (
        <div className={"lc-decision " + (DECISION_CLASS[box.decision] || "warn")}>
          {box.decision.replace(/_/g, " ")}
        </div>
      )}
      {box.error && <div className="lc-error">{box.error}</div>}

      <footer className="lc-actions">
        {active ? (
          <button className="lc-btn lc-btn-stop" onClick={() => actions.cancel(box.loanType)}>
            Stop Processing
          </button>
        ) : (
          <button className="lc-btn lc-btn-run" disabled={!canStart} onClick={() => actions.start(box.loanType)}>
            Process Documents →
          </button>
        )}
        {box.jobId && box.status === "completed" && (
          <>
            <a className="lc-link-chip lc-link-chip-primary" href={`/loan/report/${box.jobId}?kind=html`} target="_blank" rel="noreferrer">
              📄 HTML Report
            </a>
            <a className="lc-link-chip" href={`/loan/report/${box.jobId}?kind=md`} target="_blank" rel="noreferrer">
              📝 Markdown
            </a>
            <a className="lc-link-chip" href={`/loan/report/${box.jobId}?kind=json`} target="_blank" rel="noreferrer">
              ⚙️ JSON Data
            </a>
          </>
        )}
      </footer>
    </section>
  );
}
