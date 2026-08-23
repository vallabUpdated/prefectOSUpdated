import { useActiveCount } from "../hooks/useLoanJobs.js";

const DOT_CLASS = {
  starting: "running",
  running: "running",
  awaiting_approval: "awaiting",
  completed: "done",
  failed: "failed",
  rejected: "failed",
  cancelled: "cancelled",
};

export default function TopBar({ status, statusText, runIdBadge, cancelling, paused, onCancel, onPause, onResume, onBack, onSettings }) {
  const dotCls = paused ? "paused" : DOT_CLASS[status] || "";
  const active = status === "running" || status === "awaiting_approval";
  // Document processing runs independently of the pipeline; show it here so
  // leaving the landing page never looks like the job stopped.
  const docJobs = useActiveCount("loan") + useActiveCount("account");

  return (
    <div id="topbar">
      {onBack && (
        <button
          id="back-to-processing"
          onClick={onBack}
          title={
            docJobs
              ? `${docJobs} document job${docJobs > 1 ? "s" : ""} still processing — back to the processing window`
              : "Back to the processing window (Loan & Account suites)"
          }
        >
          <span aria-hidden="true">←</span> Processing
          {docJobs > 0 && <span className="tb-jobs-badge">{docJobs}</span>}
        </button>
      )}
      <div className="logo">
        <div className={"logo-hex" + (dotCls === "running" || dotCls === "awaiting" ? " live" : "")}>⬡</div>
        Prefect OS
      </div>
      <div id="run-id-badge">{runIdBadge}</div>
      <div id="global-status">
        <button
          id="pause-pipeline-btn"
          className={(active && onPause ? "visible" : "") + (paused ? " paused" : "")}
          disabled={cancelling}
          onClick={paused ? onResume : onPause}
          title={paused ? "Resume the pipeline" : "Pause the pipeline at the next stage boundary"}
        >
          {paused ? "▶ Resume" : "⏸ Pause"}
        </button>
        <button
          id="stop-pipeline-btn"
          className={active ? "visible" : ""}
          disabled={cancelling}
          onClick={onCancel}
          title="Stop the pipeline at the next stage boundary"
        >
          {cancelling ? "Stopping…" : "■ Stop pipeline"}
        </button>
        <div className={"status-dot" + (dotCls ? " " + dotCls : "")} />
        <span id="status-text">{statusText}</span>
        {onSettings && (
          <button
            id="settings-btn"
            onClick={onSettings}
            title="Settings — institution, exchange rate, policy pack, orchestrator tabs"
            aria-label="Settings"
          >
            ⚙
          </button>
        )}
      </div>
    </div>
  );
}
