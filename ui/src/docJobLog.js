/**
 * docJobLog — an event log for document processing jobs.
 *
 * loanJobStore keeps a job's *current* state (phase, counters, agents); it has
 * no memory of how the job got there. The orchestrator shows pipeline runs as a
 * running commentary, and document jobs deserve the same, so every stream event
 * is also formatted into a log line here.
 *
 * Lives at module scope alongside the store: lines are recorded whether or not
 * the orchestrator is currently mounted, so opening it mid-job shows everything
 * that already happened rather than starting from the next event.
 *
 * Line shape matches the pipeline log ({key, ts, msg, level}) so EventLog.jsx
 * renders both without changes; msg is HTML using the same highlight classes.
 */

const logs = {}; // "domain:loanType" -> array of lines
const listeners = new Set();
let seq = 0;

// A single job's commentary; older lines are dropped rather than growing forever.
const MAX_LINES = 500;

const key = (domain, loanType) => `${domain}:${loanType}`;

const PHASE_LABEL = {
  scanning: "Scanning",
  planning: "Planning",
  extracting: "Extraction",
  documents: "Documents",
  exceptions: "Exceptions",
  assessment: "Assessment",
  finished: "Finished",
};

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function notify() {
  listeners.forEach((fn) => fn());
}

function append(domain, loanType, msg, level = "info") {
  const k = key(domain, loanType);
  const next = [...(logs[k] || []), { key: ++seq, ts: Date.now(), msg, level }];
  logs[k] = next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
  notify();
}

/** A line the UI itself wants recorded (job requested, request failed, …). */
export function note(domain, loanType, msg, level = "info") {
  append(domain, loanType, msg, level);
}

/** Start a fresh log for a new run of this box. */
export function reset(domain, loanType) {
  logs[key(domain, loanType)] = [];
  notify();
}

export function clear(domain, loanType) {
  reset(domain, loanType);
}

export function getLog(domain, loanType) {
  return logs[key(domain, loanType)] || [];
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const tok = (i, o) =>
  `<span class="hb">${(i || 0).toLocaleString()} in</span> + ` +
  `<span class="hp">${(o || 0).toLocaleString()} out</span>`;

/**
 * Format one stream event. Called by loanJobStore for every event it handles,
 * so the log tracks the same truth the cards do.
 */
export function record(domain, loanType, type, d) {
  switch (type) {
    case "job_started":
      append(domain, loanType,
        `Job started · <span class="ht">${d.total || 0} document${d.total === 1 ? "" : "s"}</span>` +
        (d.mode ? ` · mode <span class="hp">${escapeHtml(d.mode)}</span>` : ""), "event");
      break;

    case "phase_changed":
      append(domain, loanType,
        `Phase <span class="hp">${PHASE_LABEL[d.phase] || escapeHtml(d.phase)}</span> started`, "event");
      break;

    case "agent_spawned":
      append(domain, loanType,
        `Agent registered: <span class="hp">${escapeHtml(d.agent?.agent_id || "agent")}</span>` +
        (d.agent?.model ? ` · ${escapeHtml(d.agent.model)}` : ""), "event");
      append(domain, loanType,
        `Agent <span class="ht">${escapeHtml(d.agent?.agent_id || "agent")}</span> is <span class="ht">ALIVE</span>`, "ok");
      break;

    case "agent_state": {
      const a = d.agent || {};
      if (a.status === "torn_down") {
        append(domain, loanType,
          `Agent <span class="hp">${escapeHtml(a.agent_id)}</span> torn down · ` +
          `${a.calls || 0} call${a.calls === 1 ? "" : "s"} · ${tok(a.tokens_in, a.tokens_out)}`, "info");
      } else if (d.tokens_in != null) {
        append(domain, loanType,
          `Tokens <span class="hp">${escapeHtml(a.agent_id)}</span>: ${tok(a.tokens_in, a.tokens_out)} · ` +
          `job total <span class="ht">${((d.tokens_in || 0) + (d.tokens_out || 0)).toLocaleString()}</span>`, "info");
      }
      break;
    }

    case "plan_ready":
      if (d.error) {
        append(domain, loanType, `Planning failed: <span class="hr">${escapeHtml(d.error)}</span>`, "error");
      } else {
        const n = (d.plan?.documents || []).length;
        append(domain, loanType,
          `Plan ready · <span class="ht">${n}</span> document${n === 1 ? "" : "s"} classified`, "ok");
      }
      break;

    case "policy_retrieved":
      append(domain, loanType,
        `Credit policy retrieved · <span class="ht">${d.clauses ?? (d.citations || []).length}</span> clauses cited`, "info");
      break;

    case "doc_started":
      append(domain, loanType,
        (d.index >= 0 ? `Document ${d.index + 1}` : "Exception") +
        `: <span class="ht">${escapeHtml(d.name)}</span>`, "event");
      break;

    case "doc_completed": {
      const failed = d.docs?.find?.((x) => x.name === d.name)?.status === "failed";
      append(domain, loanType,
        `Document <span class="${failed ? "hr" : "hg"}">${d.done || 0}/${d.total || 0}</span> ` +
        `${failed ? "failed" : "complete"} · ${tok(d.tokens_in, d.tokens_out)}`, failed ? "warn" : "ok");
      break;
    }

    case "eligibility_started":
      append(domain, loanType,
        `Assessment started · <span class="ht">${d.done || 0}/${d.total || 0}</span> documents read`, "event");
      break;

    case "job_completed":
      append(domain, loanType,
        `Job complete · ${d.decision ? `decision <span class="hg">${escapeHtml(d.decision)}</span> · ` : ""}` +
        `${tok(d.tokens_in, d.tokens_out)}` +
        (d.cost_usd != null ? ` · $${Number(d.cost_usd).toFixed(4)}` : ""), "ok");
      break;

    case "job_failed":
      append(domain, loanType, `Job failed: <span class="hr">${escapeHtml(d.error || "unknown error")}</span>`, "error");
      break;

    case "job_cancelled":
      append(domain, loanType, "Job cancelled by the operator", "warn");
      break;

    default:
      break;
  }
}

export { PHASE_LABEL };
