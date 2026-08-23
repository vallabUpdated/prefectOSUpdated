import TokenBar from "./TokenBar.jsx";
import AgentGrid from "./AgentGrid.jsx";
import EventLog from "./EventLog.jsx";
import { DOC_PHASES } from "../hooks/useDocJobRuns.js";
import { clear as clearDocLog } from "../docJobLog.js";
import { cancel as cancelDocJob } from "../loanJobStore.js";
import "../styles_docjob.css";

/**
 * DocJobRun — the orchestrator's detail view for a document processing job.
 *
 * Same three columns as a pipeline run (phases · agents · event log), reusing
 * TokenBar, AgentGrid and EventLog unchanged. What differs is the work itself:
 * phases instead of pipeline stages, and documents instead of generated files.
 */
const DOC_STATUS_CLASS = { done: "ok", failed: "bad", running: "run", skipped: "skip" };

export default function DocJobRun({ run, job }) {
  // Callers pass the job as `run` or as `job`; a missing one must not take the
  // whole orchestrator down with it.
  const doc = run || job;
  if (!doc) return null;

  const agentCount = Object.keys(doc.agents || {}).length;
  const pct = doc.total ? Math.round((doc.done / doc.total) * 100) : 0;

  return (
    <div style={{ display: "flex", flex: 1, overflow: "hidden", minWidth: 0, minHeight: 0 }}>
      <div id="left">
        <div id="stages-section">
          <div className="section-label">Document pipeline · {doc.chipName}</div>
          <div className="pipeline">
            {DOC_PHASES.map((p, i) => (
              <div className={"stage-row " + ((doc.stages || {})[p.key] || "")} key={p.key}>
                <div className="stage-num">{i + 1}</div>
                <div className="stage-info">
                  <div className="stage-name">{p.name}</div>
                  <div className="stage-sub">{p.sub}</div>
                </div>
                <div className="stage-time">
                  {p.key === "documents" && doc.total ? `${doc.done}/${doc.total}` : ""}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div id="venv-section">
          <div className="section-label">Job</div>
          <div id="venv-info">
            <div className="venv-row">
              <span className="venv-key">Status</span>
              <span className="venv-val">
                {doc.statusText}
                {doc.decision ? ` · ${doc.decision}` : ""}
              </span>
            </div>
            <div className="venv-row">
              <span className="venv-key">Input</span>
              <span className="venv-val">{doc.inputPath || "—"}</span>
            </div>
            <div className="venv-row">
              <span className="venv-key">Output</span>
              <span className="venv-val">{doc.runFolder || doc.outputPath || "—"}</span>
            </div>
            <div className="venv-row">
              <span className="venv-key">Mode</span>
              <span className="venv-val">{doc.mode || "—"}</span>
            </div>
            <div className="venv-row">
              <span className="venv-key">Elapsed</span>
              <span className="venv-val">
                {doc.elapsedS ? `${doc.elapsedS}s` : "—"}
                {doc.costUsd != null ? ` · $${Number(doc.costUsd).toFixed(4)}` : ""}
              </span>
            </div>
          </div>

          {doc.total > 0 && (
            <div className="dj-progress" title={`${doc.done} of ${doc.total} documents`}>
              <div className="dj-progress-fill" style={{ width: `${pct}%` }} />
            </div>
          )}

          {doc.error && <div className="dj-error">{doc.error}</div>}

          {doc.active && (
            <button className="dj-cancel" onClick={() => cancelDocJob(doc.domain, doc.loanType)}>
              ■ Stop this job
            </button>
          )}
          {!doc.active && doc.jobId && (
            <a className="dj-report" href={`/loan/report/${doc.jobId}?kind=html`} target="_blank" rel="noreferrer">
              ⬇ Open the report
            </a>
          )}
        </div>
      </div>

      <div id="center">
        <TokenBar tokIn={doc.tokIn} tokOut={doc.tokOut} budgetUsed={agentCount} agents={doc.agents} />
        <AgentGrid agents={doc.agents} />
      </div>

      <div id="right">
        <div id="docs-section">
          <div className="section-label">Documents{doc.total ? ` · ${doc.done}/${doc.total}` : ""}</div>
          <div className="dj-doc-list">
            {(doc.docs || []).length === 0 && <div className="dj-doc-empty">No documents reported yet</div>}
            {(doc.docs || []).map((d) => (
              <div className={"dj-doc " + (DOC_STATUS_CLASS[d.status] || "")} key={d.name}>
                <span className="dj-doc-name" title={d.error || d.name}>{d.name}</span>
                <span className="dj-doc-status">{d.status}</span>
              </div>
            ))}
          </div>
        </div>

        <EventLog log={doc.log || []} onClear={() => clearDocLog(doc.domain, doc.loanType)} />
      </div>
    </div>
  );
}
