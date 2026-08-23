const DOT_CLASS = {
  starting: "running",
  running: "running",
  awaiting_approval: "awaiting",
  completed: "done",
  failed: "failed",
  rejected: "failed",
  cancelled: "cancelled",
};

// Selecting this chip means "show the pipeline pane, not a document job".
// The same id the orchestrator checks for when routing a chip click.
const PIPELINE_CHIP = "__pipeline__";

/**
 * RunSwitcher — one chip per run across the top of the Live run tab.
 *
 * Two kinds of run share the strip: pipeline runs and document processing jobs.
 * Callers may pass the jobs merged into `runs` or separately as `docRuns` (with
 * `activeDocRunId` saying which is selected); either way they end up as chips,
 * document jobs first.
 */
export default function RunSwitcher({
  runs = [],
  activeRunId,
  onSelect,
  view,
  onViewChange,
  docRuns = [],
  activeDocRunId = null,
}) {
  const extras = docRuns.filter((d) => !runs.some((r) => r.runId === d.runId));
  const all = [...extras, ...runs];
  const selected = activeDocRunId || activeRunId;

  // Watching a document job with no pipeline run to switch back to would be a
  // dead end — the pipeline pane needs a chip of its own.
  if (all.length && !runs.length) {
    all.push({
      runId: PIPELINE_CHIP,
      chipName: "＋ Pipeline run",
      statusText: "start a run",
      status: "idle",
      activity: "Start a governed pipeline run",
    });
  }

  // One pipeline run needs no switcher, but a document job always does: it is
  // the only way back to the pipeline pane once a job is being watched.
  if (all.length < 2 && !all.some((r) => r.kind === "doc")) return null;

  return (
    <div id="run-switcher">
      <span className="rs-label">Runs</span>
      {all.map((r) => {
        const dotCls = r.paused ? "paused" : DOT_CLASS[r.status] || "";
        const badge = r.paused ? "paused" : r.approval ? "approval" : r.statusText;
        return (
          <button
            key={r.runId}
            className={"run-chip" + (r.runId === selected ? " active" : "")}
            onClick={() => onSelect(r.runId)}
            title={r.activity}
          >
            <span className={"status-dot" + (dotCls ? " " + dotCls : "")} />
            <span className="rc-name">{r.chipName || `Run ${r.index}`}</span>
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
