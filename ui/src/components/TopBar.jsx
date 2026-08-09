const DOT_CLASS = {
  starting: "running",
  running: "running",
  awaiting_approval: "awaiting",
  completed: "done",
  failed: "failed",
  rejected: "failed",
  cancelled: "cancelled",
};

export default function TopBar({ status, statusText, runIdBadge, cancelling, paused, onCancel, onPause, onResume }) {
  const dotCls = paused ? "paused" : DOT_CLASS[status] || "";
  const active = status === "running" || status === "awaiting_approval";

  return (
    <div id="topbar">
      <div className="logo">
        <div className={"logo-hex" + (dotCls === "running" || dotCls === "awaiting" ? " live" : "")}>⬡</div>
        Prefect OS
      </div>
      <div id="run-id-badge">{runIdBadge}</div>
      <div id="global-status">
        <button
          id="pause-pipeline-btn"
          className={(active ? "visible" : "") + (paused ? " paused" : "")}
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
      </div>
    </div>
  );
}
