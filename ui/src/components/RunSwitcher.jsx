const DOT_CLASS = {
  starting: "running",
  running: "running",
  awaiting_approval: "awaiting",
  completed: "done",
  failed: "failed",
  rejected: "failed",
  cancelled: "cancelled",
};

export default function RunSwitcher({ runs, activeRunId, onSelect, view, onViewChange }) {
  if (runs.length < 2) return null;

  return (
    <div id="run-switcher">
      <span className="rs-label">Runs</span>
      {runs.map((r) => {
        const dotCls = r.paused ? "paused" : DOT_CLASS[r.status] || "";
        const badge = r.paused ? "paused" : r.approval ? "approval" : r.statusText;
        return (
          <button
            key={r.runId}
            className={"run-chip" + (r.runId === activeRunId ? " active" : "")}
            onClick={() => onSelect(r.runId)}
            title={r.activity}
          >
            <span className={"status-dot" + (dotCls ? " " + dotCls : "")} />
            <span className="rc-name">Run {r.index}</span>
            <span className="rc-status">{badge}</span>
          </button>
        );
      })}
      <button
        id="view-toggle"
        onClick={() => onViewChange(view === "board" ? "detail" : "board")}
        title={view === "board" ? "Show one run in full detail" : "Show all runs side by side"}
      >
        {view === "board" ? "▤ Detail view" : "⊞ All runs"}
      </button>
    </div>
  );
}
