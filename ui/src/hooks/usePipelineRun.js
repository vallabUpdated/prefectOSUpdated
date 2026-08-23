import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { actor as ledgerActor } from "../activityLedger.js";

const MAX_AGENTS = 10;

const STAGE_NAMES = {
  plan: "Planning",
  spec: "Specification",
  env: "Environment",
  execute: "Code generation",
  test: "Testing",
  launch: "Launch app",
};

function basename(p) {
  return p ? p.split(/[/\\]/).pop() : "—";
}

// State of one pipeline run. The hook tracks many of these concurrently
// (keyed by runId) — the UI shows the "active" (selected) one.
const initialRunState = {
  runId: null,
  activity: "",
  status: "starting", // starting | running | awaiting_approval | completed | failed | rejected | cancelled
  statusText: "starting…",
  runIdBadge: "starting…",
  cancelling: false,
  paused: false,
  agents: {}, // agent_id -> record
  budgetUsed: 0,
  tokIn: 0,
  tokOut: 0,
  stages: {}, // stage -> "" | active | done | failed
  stageTimes: {}, // stage -> "3.2s"
  log: [], // {key, ts, msg, level}
  approval: null, // {stage, content, editable}
  filePreview: null, // {filename, content}
  output: { project: "", venv: "", files: [] },
  app: { show: false, running: false, url: "", port: 0, pid: 0, framework: "", cmd: "" },
};

// Shown when no run exists / is selected yet.
const idleRunState = {
  ...initialRunState,
  status: "idle",
  statusText: "idle",
  runIdBadge: "no active run",
};

const initialState = {
  activeRunId: null,
  order: [], // runIds in start order
  runs: {}, // runId -> run state
};

let logSeq = 0;

function runReducer(state, action) {
  switch (action.type) {
    case "PIPELINE_STARTED":
      return {
        ...state,
        status: "running",
        statusText: "running",
        log: appendLog(state.log, `Pipeline started · <span class="ht">${escapeHtml(action.activity)}</span>`, "info"),
      };

    case "PROJECT_CREATED":
      return {
        ...state,
        runIdBadge: action.thread_id ? action.thread_id.slice(0, 30) + "…" : state.runIdBadge,
        log: appendLog(state.log, `Project: <span class="ht">${escapeHtml(basename(action.project_dir))}</span>`, "info"),
      };

    case "STAGE_STARTED":
      return {
        ...state,
        stages: { ...state.stages, [action.stage]: "active" },
        log: appendLog(state.log, `Stage <span class="hp">${STAGE_NAMES[action.stage] || action.stage}</span> started`, "event"),
      };

    case "STAGE_COMPLETED":
      return {
        ...state,
        stages: { ...state.stages, [action.stage]: "done" },
        stageTimes: action.elapsedText
          ? { ...state.stageTimes, [action.stage]: action.elapsedText }
          : state.stageTimes,
        log: appendLog(state.log, `Stage <span class="hg">${STAGE_NAMES[action.stage] || action.stage}</span> complete`, "ok"),
      };

    case "AGENT_FILE_PREVIEW":
      return {
        ...state,
        filePreview: { filename: action.filename, content: action.content },
        budgetUsed: action.budget_used,
        log: appendLog(state.log, `Agent file: <span class="hp">${escapeHtml(action.filename)}</span> · budget ${action.budget_used}/${action.budget_max}`, "event"),
      };

    case "AGENT_REGISTERED":
      return {
        ...state,
        agents: { ...state.agents, [action.agent_id]: { ...action.data, status: "PENDING" } },
        budgetUsed: Math.max(state.budgetUsed, action.slot),
        log: appendLog(state.log, `Agent registered: <span class="hp">${action.agent_id}</span> · slot ${action.slot}`, "event"),
      };

    case "AGENT_ALIVE": {
      const existing = state.agents[action.agent_id];
      if (!existing) return { ...state, log: appendLog(state.log, `Agent <span class="ht">${action.agent_id}</span> is <span class="ht">ALIVE</span>`, "ok") };
      return {
        ...state,
        agents: { ...state.agents, [action.agent_id]: { ...existing, status: "ALIVE", spawned_at: action.spawned_at } },
        log: appendLog(state.log, `Agent <span class="ht">${action.agent_id}</span> is <span class="ht">ALIVE</span>`, "ok"),
      };
    }

    case "AGENT_TORN_DOWN": {
      const existing = state.agents[action.agent_id];
      const next = existing
        ? { ...existing, status: "TORN_DOWN", elapsed_s: action.elapsed_s, output_chars: action.output_chars }
        : undefined;
      return {
        ...state,
        agents: next ? { ...state.agents, [action.agent_id]: next } : state.agents,
        log: appendLog(state.log, `Agent <span class="hp">${action.agent_id}</span> torn down · ${action.elapsed_s}s · ${action.output_chars} chars`, "info"),
      };
    }

    case "AGENT_FAILED": {
      const existing = state.agents[action.agent_id];
      return {
        ...state,
        agents: existing ? { ...state.agents, [action.agent_id]: { ...existing, status: "FAILED" } } : state.agents,
        log: appendLog(state.log, `Agent <span class="hr">${action.agent_id}</span> FAILED: ${escapeHtml(action.error)}`, "error"),
      };
    }

    case "TOKEN_UPDATE": {
      const existing = state.agents[action.agent_id];
      const agents = existing
        ? {
            ...state.agents,
            [action.agent_id]: {
              ...existing,
              input_tokens: (existing.input_tokens || 0) + action.input_tokens,
              output_tokens: (existing.output_tokens || 0) + action.output_tokens,
            },
          }
        : state.agents;
      return {
        ...state,
        agents,
        tokIn: action.total_input_tokens,
        tokOut: action.total_output_tokens,
        log: appendLog(
          state.log,
          `Tokens <span class="hp">${action.agent_id}</span>: <span class="hb">${action.input_tokens.toLocaleString()} in</span> + ` +
            `<span class="hp">${action.output_tokens.toLocaleString()} out</span> · total <span class="ht">${(action.total_tokens || 0).toLocaleString()}</span>`,
          "info"
        ),
      };
    }

    case "APPROVAL_REQUIRED":
      return {
        ...state,
        status: "awaiting_approval",
        statusText: state.paused ? "paused" : "awaiting approval",
        approval: { stage: action.stage, content: action.content || "", editable: !!action.editable },
        log: appendLog(state.log, `Approval gate: <span class="ha">${action.stage}</span>`, "warn"),
      };

    // Broadcast from the server: someone (this window or another) decided the
    // open gate. Ignored when this window already applied it optimistically,
    // so the log never shows the decision twice.
    case "APPROVAL_DECIDED": {
      if (!state.approval) return state;
      const who = action.decided_by?.name ? ` · by ${escapeHtml(action.decided_by.name)}` : "";
      return {
        ...state,
        status: "running",
        statusText: state.paused ? "paused" : "running",
        approval: null,
        filePreview: null,
        log: appendLog(state.log, `Decision: <span class="${action.decision === "approve" ? "hg" : "hr"}">${escapeHtml(action.decision)}</span>${who}`, "event"),
      };
    }

    case "APPROVAL_SENT":
      return {
        ...state,
        status: "running",
        statusText: state.paused ? "paused" : "running",
        approval: null,
        filePreview: null,
        log: appendLog(state.log, `Decision: <span class="${action.decision === "approve" ? "hg" : "hr"}">${action.decision}</span>`, "event"),
      };

    case "LOG":
      return { ...state, log: appendLog(state.log, action.msg, action.level || "info") };

    case "PIPELINE_COMPLETED": {
      const doneStages = {};
      Object.keys(state.stages).forEach((s) => (doneStages[s] = "done"));
      ["plan", "spec", "env", "execute", "test"].forEach((s) => (doneStages[s] = "done"));
      return {
        ...state,
        status: "completed",
        statusText: "completed",
        paused: false,
        stages: doneStages,
        output: {
          project: basename(action.project_dir),
          venv: action.venv_dir ? basename(action.venv_dir) : "(skipped)",
          files: action.files || [],
        },
        log: appendLog(state.log, `Pipeline complete · total <span class="ht">${(action.total_tokens || 0).toLocaleString()}</span> tokens`, "ok"),
      };
    }

    case "APP_LAUNCHED":
      return {
        ...state,
        app: {
          show: true,
          running: true,
          url: action.url,
          port: action.port,
          pid: action.pid,
          framework: action.framework,
          cmd: action.cmd,
        },
        log: appendLog(state.log, `App launched: <a href="${action.url}" target="_blank" style="color:var(--teal)">${action.url}</a> · PID ${action.pid}`, "ok"),
      };

    case "APP_STOPPED":
      return {
        ...state,
        app: { ...state.app, show: true, running: false, url: "" },
        log: appendLog(state.log, `App stopped · PID ${action.pid}`, "warn"),
      };

    case "PIPELINE_PAUSED":
      return {
        ...state,
        paused: true,
        statusText: "paused",
        log: appendLog(state.log, "Pipeline paused — holding at the next stage boundary", "warn"),
      };

    case "PIPELINE_RESUMED":
      return {
        ...state,
        paused: false,
        statusText: state.status === "awaiting_approval" ? "awaiting approval" : "running",
        log: appendLog(state.log, "Pipeline resumed", "ok"),
      };

    case "PIPELINE_CANCELLED":
      return {
        ...state,
        status: "cancelled",
        statusText: "cancelled",
        cancelling: false,
        paused: false,
        stages: markActiveAsFailed(state.stages),
        log: appendLog(state.log, `Pipeline stopped: ${escapeHtml(action.reason)}`, "warn"),
      };

    case "PIPELINE_REJECTED":
      return {
        ...state,
        status: "rejected",
        statusText: "rejected",
        paused: false,
        log: appendLog(state.log, `Rejected: ${escapeHtml(action.reason)}`, "warn"),
      };

    case "PIPELINE_FAILED":
      return {
        ...state,
        status: "failed",
        statusText: "failed",
        paused: false,
        stages: markActiveAsFailed(state.stages),
        log: appendLog(state.log, `Failed: <span class="hr">${escapeHtml(action.reason)}</span>`, "error"),
      };

    case "CANCELLING":
      return { ...state, cancelling: true, log: appendLog(state.log, "Pipeline stop requested — waiting for current stage to finish…", "warn") };

    case "CANCEL_FAILED":
      return { ...state, cancelling: false, log: appendLog(state.log, `Cancel failed: ${escapeHtml(action.msg)}`, "error") };

    case "CLEAR_LOG":
      return { ...state, log: [] };

    default:
      return state;
  }
}

function reducer(state, action) {
  switch (action.type) {
    case "RUN_STARTING": {
      const run = {
        ...initialRunState,
        runId: action.tempId,
        activity: action.activity,
        log: appendLog([], `Starting run · <span class="ht">${escapeHtml(action.activity)}</span>`, "info"),
      };
      return {
        activeRunId: action.tempId,
        order: [...state.order, action.tempId],
        runs: { ...state.runs, [action.tempId]: run },
      };
    }

    case "RUN_STARTED": {
      // The server assigned the real run id — re-key the temp entry.
      const run = state.runs[action.tempId];
      if (!run) return state;
      const runs = { ...state.runs };
      delete runs[action.tempId];
      runs[action.runId] = {
        ...run,
        runId: action.runId,
        runIdBadge: action.runId,
        log: appendLog(run.log, `Run started · <span class="ht">${action.runId}</span>`, "info"),
      };
      return {
        activeRunId: state.activeRunId === action.tempId ? action.runId : state.activeRunId,
        order: state.order.map((id) => (id === action.tempId ? action.runId : id)),
        runs,
      };
    }

    // A run this window did not start (server already knows it): make room for
    // it, then its replayed events rebuild log/stages/agents/tokens/gate.
    case "RUN_ADOPTED": {
      if (state.runs[action.runId]) return state;
      const run = {
        ...initialRunState,
        runId: action.runId,
        runIdBadge: action.runId,
        activity: action.activity || "",
        status: "running",
        statusText: "replaying…",
        log: appendLog([], `Re-attached to run <span class="ht">${escapeHtml(action.runId)}</span> — replaying its history`, "info"),
      };
      return {
        activeRunId: state.activeRunId || action.runId,
        order: [...state.order, action.runId],
        runs: { ...state.runs, [action.runId]: run },
      };
    }

    case "SET_ACTIVE_RUN":
      return state.runs[action.runId] ? { ...state, activeRunId: action.runId } : state;

    default: {
      // Per-run action — delegate to the run's reducer.
      const runId = action.runId;
      const run = runId != null ? state.runs[runId] : undefined;
      if (!run) return state;
      const next = runReducer(run, action);
      if (next === run) return state;
      return { ...state, runs: { ...state.runs, [runId]: next } };
    }
  }
}

function appendLog(log, msg, level) {
  return [...log, { key: ++logSeq, ts: Date.now(), msg, level }];
}

function markActiveAsFailed(stages) {
  const next = { ...stages };
  Object.keys(next).forEach((s) => {
    if (next[s] === "active") next[s] = "failed";
  });
  return next;
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

const ACTIVE_STATUSES = ["starting", "running", "awaiting_approval"];

// Every server event carries an ISO `ts`. Prefer it over the wall clock so
// replayed history reproduces the original timings.
function eventTime(data) {
  const t = data && data.ts ? Date.parse(data.ts) : NaN;
  return Number.isNaN(t) ? Date.now() : t;
}

export default function usePipelineRun() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const evtSrcRef = useRef({}); // runId -> EventSource
  const lastSeqRef = useRef({}); // runId -> highest event seq applied (replay resume point)
  const stageTimersRef = useRef({}); // runId -> {stage: t0}
  const activeRunIdRef = useRef(null);
  const runsRef = useRef(state.runs);

  useEffect(() => {
    activeRunIdRef.current = state.activeRunId;
    runsRef.current = state.runs;
  });

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const res = await fetch("/runs");
      const data = await res.json();
      setHistory((data.runs || []).slice().reverse());
    } catch {
      setHistory([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const closeStream = useCallback((runId) => {
    const src = evtSrcRef.current[runId];
    if (src) {
      src.close();
      delete evtSrcRef.current[runId];
    }
  }, []);

  // Close every stream on unmount
  useEffect(
    () => () => {
      Object.values(evtSrcRef.current).forEach((src) => src.close());
      evtSrcRef.current = {};
    },
    []
  );

  const handleEvent = useCallback(
    (runId, type, data) => {
      switch (type) {
        case "pipeline_started":
          dispatch({ type: "PIPELINE_STARTED", runId, activity: data.activity });
          break;
        case "project_created":
          dispatch({ type: "PROJECT_CREATED", runId, thread_id: data.thread_id, project_dir: data.project_dir });
          break;
        case "stage_started":
          // Server timestamp, not wall clock: a replayed run then reports the
          // durations it actually took, not the millisecond it was replayed in.
          (stageTimersRef.current[runId] ||= {})[data.stage] = eventTime(data);
          dispatch({ type: "STAGE_STARTED", runId, stage: data.stage });
          break;
        case "stage_completed": {
          const timers = stageTimersRef.current[runId] || {};
          const start = timers[data.stage];
          const elapsedText = start ? ((eventTime(data) - start) / 1000).toFixed(1) + "s" : null;
          timers[data.stage] = null;
          dispatch({ type: "STAGE_COMPLETED", runId, stage: data.stage, elapsedText });
          break;
        }
        case "agent_file_preview":
          dispatch({ type: "AGENT_FILE_PREVIEW", runId, filename: data.filename, content: data.content, budget_used: data.budget_used, budget_max: data.budget_max });
          break;
        case "agent_registered":
          dispatch({ type: "AGENT_REGISTERED", runId, agent_id: data.agent_id, slot: data.slot, data });
          break;
        case "agent_alive":
          dispatch({ type: "AGENT_ALIVE", runId, agent_id: data.agent_id, spawned_at: data.spawned_at });
          break;
        case "agent_torn_down":
          dispatch({ type: "AGENT_TORN_DOWN", runId, agent_id: data.agent_id, elapsed_s: data.elapsed_s, output_chars: data.output_chars });
          break;
        case "agent_failed":
          dispatch({ type: "AGENT_FAILED", runId, agent_id: data.agent_id, error: data.error });
          break;
        case "token_update":
          dispatch({
            type: "TOKEN_UPDATE",
            runId,
            agent_id: data.agent_id,
            input_tokens: data.input_tokens,
            output_tokens: data.output_tokens,
            total_input_tokens: data.total_input_tokens,
            total_output_tokens: data.total_output_tokens,
            total_tokens: data.total_tokens,
          });
          break;
        case "approval_required":
          dispatch({ type: "APPROVAL_REQUIRED", runId, stage: data.stage, content: data.content, editable: data.editable });
          break;
        case "approval_decided":
          dispatch({ type: "APPROVAL_DECIDED", runId, decision: data.decision, decided_by: data.decided_by });
          break;
        case "log":
          dispatch({ type: "LOG", runId, msg: data.msg, level: data.level });
          break;
        case "pipeline_completed":
          dispatch({ type: "PIPELINE_COMPLETED", runId, project_dir: data.project_dir, venv_dir: data.venv_dir, files: data.files, total_tokens: data.total_tokens });
          loadHistory();
          break;
        case "app_launched":
          dispatch({ type: "APP_LAUNCHED", runId, url: data.url, port: data.port, pid: data.pid, framework: data.framework, cmd: data.cmd });
          break;
        case "app_stopped":
          dispatch({ type: "APP_STOPPED", runId, pid: data.pid });
          break;
        case "pipeline_paused":
          dispatch({ type: "PIPELINE_PAUSED", runId });
          break;
        case "pipeline_resumed":
          dispatch({ type: "PIPELINE_RESUMED", runId });
          break;
        case "pipeline_cancelled":
          dispatch({ type: "PIPELINE_CANCELLED", runId, reason: data.reason });
          break;
        case "pipeline_rejected":
          dispatch({ type: "PIPELINE_REJECTED", runId, reason: data.reason });
          break;
        case "pipeline_failed":
          dispatch({ type: "PIPELINE_FAILED", runId, reason: data.reason });
          break;
        case "stream_end":
          closeStream(runId);
          break;
        default:
          break;
      }
    },
    [closeStream, loadHistory]
  );

  // Attach (or re-attach) to a run's event stream. The server replays every
  // event the run has already emitted before going live, so this is all that
  // is needed to rebuild the orchestrator view for a run in progress — or one
  // that finished before this window was ever opened.
  const attachStream = useCallback(
    (runId) => {
      if (evtSrcRef.current[runId]) return;
      const from = lastSeqRef.current[runId] || 0;
      const src = new EventSource(`/stream/${runId}?from=${from}`);
      evtSrcRef.current[runId] = src;

      const types = [
        "pipeline_started", "project_created", "stage_started", "stage_completed",
        "agent_file_preview", "agent_registered", "agent_alive", "agent_torn_down", "agent_failed",
        "token_update", "approval_required", "approval_decided", "log", "pipeline_completed",
        "pipeline_rejected", "pipeline_failed", "pipeline_cancelled", "pipeline_paused",
        "pipeline_resumed", "app_launched", "app_stopped", "stream_end", "heartbeat",
      ];
      types.forEach((t) => {
        src.addEventListener(t, (e) => {
          try {
            const data = JSON.parse(e.data);
            // Remember how far we got: a reconnect resumes from here instead
            // of replaying events this window has already applied.
            if (data.seq) lastSeqRef.current[runId] = Math.max(lastSeqRef.current[runId] || 0, data.seq);
            handleEvent(runId, t, data);
          } catch {
            /* ignore malformed event */
          }
        });
      });

      src.onerror = () => {
        const run = runsRef.current[runId];
        const terminal = run && !ACTIVE_STATUSES.includes(run.status);
        if (terminal) {
          // Run already finished — the server closing the stream is expected.
          closeStream(runId);
        } else if (src.readyState === EventSource.CLOSED) {
          // Fatal (e.g. 404 because a server restart lost the in-memory run):
          // the browser will not retry, and the run cannot be driven anymore.
          closeStream(runId);
          dispatch({
            type: "PIPELINE_FAILED",
            runId,
            reason: "live stream lost — the server no longer knows this run (was it restarted?)",
          });
        } else {
          // Transient drop — EventSource is auto-reconnecting.
          dispatch({ type: "LOG", runId, msg: "SSE connection interrupted — reconnecting…", level: "warn" });
        }
      };
    },
    [handleEvent, closeStream]
  );

  // On load, adopt every run the server already knows about and replay it.
  // This is what makes opening (or reloading) the orchestrator window show the
  // full log and progress of work that started before the window existed.
  useEffect(() => {
    let dropped = false;
    (async () => {
      try {
        const res = await fetch("/live-runs");
        const data = await res.json();
        if (dropped) return;
        const adopted = [];
        (data.runs || []).forEach((r) => {
          if (!r.run_id || evtSrcRef.current[r.run_id]) return;
          dispatch({ type: "RUN_ADOPTED", runId: r.run_id, activity: r.activity, status: r.status });
          attachStream(r.run_id);
          adopted.push(r);
        });
        // Open on the newest run still in flight; failing that, the newest one.
        const live = adopted.filter((r) => !r.replay);
        const focus = (live.length ? live : adopted).slice(-1)[0];
        if (focus) dispatch({ type: "SET_ACTIVE_RUN", runId: focus.run_id });
      } catch {
        /* no server-side runs to re-attach to */
      }
    })();
    return () => {
      dropped = true;
    };
  }, [attachStream]);

  const startRun = useCallback(
    async (activity, codebase = "", extras = null) => {
      const tempId = `local-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
      dispatch({ type: "RUN_STARTING", tempId, activity });

      try {
        // Who is starting the run, so it lands in that key's ledger. The key
        // travels no further than the ledger's file name (see activity_ledger).
        const body = { activity, actor: ledgerActor(), ...(extras || {}) };
        if (codebase) body.codebase = codebase;
        const res = await fetch("/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to start");

        const runId = data.run_id;
        dispatch({ type: "RUN_STARTED", tempId, runId });
        attachStream(runId);
      } catch (e) {
        dispatch({ type: "PIPELINE_FAILED", runId: tempId, reason: e.message });
      }
    },
    [attachStream]
  );

  const selectRun = useCallback((runId) => {
    dispatch({ type: "SET_ACTIVE_RUN", runId });
  }, []);

  // Actions accept an optional explicit runId (used by the board view's
  // per-card controls); anything non-string (e.g. a click event when passed
  // directly as an onClick handler) falls back to the selected run.
  const resolveRunId = useCallback(
    (maybeId) => (typeof maybeId === "string" && maybeId ? maybeId : activeRunIdRef.current),
    []
  );

  const sendApproval = useCallback(async (decision, editedContent = null, targetRunId = null, extras = null) => {
    const runId = resolveRunId(targetRunId);
    if (!runId) return;
    dispatch({ type: "APPROVAL_SENT", runId, decision });
    try {
      const body = { decision, actor: ledgerActor(), ...(extras || {}) };
      if (decision === "approve" && editedContent != null) body.content = editedContent;
      await fetch(`/approve/${runId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (e) {
      dispatch({ type: "LOG", runId, msg: `Failed to send decision: ${e.message}`, level: "error" });
    }
  }, [resolveRunId]);

  const cancelPipeline = useCallback(async (targetRunId = null) => {
    const runId = resolveRunId(targetRunId);
    if (!runId) return;
    dispatch({ type: "CANCELLING", runId });
    try {
      const res = await fetch(`/cancel/${runId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) dispatch({ type: "CANCEL_FAILED", runId, msg: data.detail || "unknown" });
    } catch (e) {
      dispatch({ type: "CANCEL_FAILED", runId, msg: e.message });
    }
  }, [resolveRunId]);

  const pausePipeline = useCallback(async (targetRunId = null) => {
    const runId = resolveRunId(targetRunId);
    if (!runId) return;
    try {
      const res = await fetch(`/pause/${runId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) dispatch({ type: "LOG", runId, msg: `Pause failed: ${escapeHtml(data.detail || "unknown error")}`, level: "error" });
    } catch (e) {
      dispatch({ type: "LOG", runId, msg: `Pause error: ${escapeHtml(e.message)}`, level: "error" });
    }
  }, [resolveRunId]);

  const resumePipeline = useCallback(async (targetRunId = null) => {
    const runId = resolveRunId(targetRunId);
    if (!runId) return;
    try {
      const res = await fetch(`/resume/${runId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) dispatch({ type: "LOG", runId, msg: `Resume failed: ${escapeHtml(data.detail || "unknown error")}`, level: "error" });
    } catch (e) {
      dispatch({ type: "LOG", runId, msg: `Resume error: ${escapeHtml(e.message)}`, level: "error" });
    }
  }, [resolveRunId]);

  const stopApp = useCallback(async (targetRunId = null) => {
    const runId = resolveRunId(targetRunId);
    if (!runId) return;
    try {
      const res = await fetch(`/stop/${runId}`, { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        dispatch({ type: "APP_STOPPED", runId, pid: data.pid });
      } else {
        dispatch({ type: "LOG", runId, msg: `Stop failed: ${data.detail || "unknown error"}`, level: "error" });
      }
    } catch (e) {
      dispatch({ type: "LOG", runId, msg: `Stop error: ${e.message}`, level: "error" });
    }
  }, [resolveRunId]);

  const clearLog = useCallback(() => {
    const runId = activeRunIdRef.current;
    if (runId) dispatch({ type: "CLEAR_LOG", runId });
  }, []);

  // Poll app status every 5s for every run whose generated app claims to be running.
  useEffect(() => {
    const id = setInterval(async () => {
      for (const [runId, run] of Object.entries(runsRef.current)) {
        if (!run.app.running || !run.app.pid || runId.startsWith("local-")) continue;
        try {
          const res = await fetch(`/app-status/${runId}`);
          const data = await res.json();
          if (!data.running) {
            dispatch({ type: "APP_STOPPED", runId, pid: run.app.pid });
          }
        } catch {
          /* ignore transient polling errors */
        }
      }
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const activeRun = state.runs[state.activeRunId] || idleRunState;
  // Full per-run state (plus 1-based index) — the board view renders cards
  // straight from these; the switcher uses the summary fields.
  const runList = state.order.map((id, i) => ({ ...state.runs[id], index: i + 1 }));
  const activeCount = runList.filter((r) => ACTIVE_STATUSES.includes(r.status)).length;

  return {
    state: activeRun,
    runs: runList,
    activeRunId: state.activeRunId,
    activeCount,
    history,
    historyLoading,
    actions: { startRun, selectRun, sendApproval, cancelPipeline, pausePipeline, resumePipeline, stopApp, loadHistory, clearLog },
  };
}

export { MAX_AGENTS, STAGE_NAMES };
