import PromptPanel from "./PromptPanel.jsx";

const DOT_CLASS = {
  starting: "running",
  running: "running",
  awaiting_approval: "awaiting",
  completed: "done",
  failed: "failed",
  rejected: "failed",
  cancelled: "cancelled",
};

const STAGE_ORDER = ["plan", "spec", "env", "execute", "test", "launch"];
const STAGE_LABELS = {
  plan: "Planning",
  spec: "Specification",
  env: "Environment",
  execute: "Code generation",
  test: "Testing",
  launch: "Launch app",
};

function RunCard({ run, actions, onOpen }) {
  const dotCls = run.paused ? "paused" : DOT_CLASS[run.status] || "";
  const active = run.status === "starting" || run.status === "running" || run.status === "awaiting_approval";
  const totalTok = (run.tokIn || 0) + (run.tokOut || 0);

  return (
    <div className={"run-card" + (run.approval && !run.paused ? " awaiting" : "")}>
      <div className="rc-header">
        <span className={"status-dot" + (dotCls ? " " + dotCls : "")} />
        <span className="rc-title">Run {run.index}</span>
        <span className="rc-badge">{run.paused ? "paused" : run.statusText}</span>
        <button className="rc-open" onClick={() => onOpen(run.runId)} title="Open this run in the full detail view">
          Open ▸
        </button>
      </div>

      <div className="rc-activity" title={run.activity}>{run.activity}</div>

      <div className="rc-stages">
        {STAGE_ORDER.map((s) => (
          <div
            key={s}
            className={"rc-seg" + (run.stages[s] ? " " + run.stages[s] : "")}
            title={`${STAGE_LABELS[s]}${run.stageTimes[s] ? " · " + run.stageTimes[s] : ""}`}
          />
        ))}
      </div>

      <div className="rc-meta">
        <span>tokens {totalTok.toLocaleString()}</span>
        <span>budget {run.budgetUsed}/10</span>
        {run.app.running && run.app.url && (
          <a href={run.app.url} target="_blank" rel="noreferrer">app ↗</a>
        )}
        {run.output.project && <span title={run.output.project}>{run.output.files.length} files</span>}
      </div>

      {run.approval && (
        <div className="rc-approval">
          <div className="rc-approval-stage">⚠ Approval required · {run.approval.stage}</div>
          <div className="rc-btns">
            <button className="rc-approve" onClick={() => actions.sendApproval("approve", null, run.runId)}>
              ✓ Approve
            </button>
            <button className="rc-reject" onClick={() => actions.sendApproval("reject", null, run.runId)}>
              ✕ Reject
            </button>
            <button className="rc-review" onClick={() => onOpen(run.runId)} title="Review the full content before deciding">
              Review…
            </button>
          </div>
        </div>
      )}

      {active && (
        <div className="rc-btns">
          <button
            className={"rc-ctl" + (run.paused ? " rc-resume" : "")}
            onClick={() => (run.paused ? actions.resumePipeline(run.runId) : actions.pausePipeline(run.runId))}
          >
            {run.paused ? "▶ Resume" : "⏸ Pause"}
          </button>
          <button
            className="rc-ctl rc-stop"
            disabled={run.cancelling}
            onClick={() => actions.cancelPipeline(run.runId)}
          >
            {run.cancelling ? "Stopping…" : "■ Stop"}
          </button>
        </div>
      )}
    </div>
  );
}

export default function RunBoard({ runs, actions, onOpen, draftPrompt }) {
  return (
    <div id="run-board">
      {runs.map((r) => (
        <RunCard key={r.runId} run={r} actions={actions} onOpen={onOpen} />
      ))}
      <div className="run-card new-run-card">
        <div className="rc-header">
          <span className="rc-title">Start another run</span>
        </div>
        <PromptPanel onRun={actions.startRun} activeCount={runs.length} initialPrompt={draftPrompt} autoFocus={false} />
      </div>
    </div>
  );
}
