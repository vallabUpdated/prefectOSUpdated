/**
 * loanJobStore — processing state that outlives the screens rendering it.
 *
 * A job runs on the server for as long as it takes; the operator should be free
 * to switch between Loan and Account, open the orchestrator, or reload the page
 * without losing it. So the boxes, their live progress, and the EventSource for
 * each run live here at module scope rather than in component state. React
 * components subscribe (see useLoanJobs) and are pure readers — mounting and
 * unmounting them neither starts nor stops anything.
 *
 * Two levels of continuity:
 *   • Navigation (component unmount) — the store and its open streams are
 *     untouched, so returning to a screen shows the run exactly where it got to.
 *   • Reload (the whole tab goes away) — active job ids are persisted, and on
 *     the next load each one is re-checked against GET /loan/jobs/<id> and its
 *     stream re-opened if it is still going.
 */

import * as docLog from "./docJobLog.js";
import { record as recordActivity } from "./activityLedger.js";

// The loan boxes keep their original key so existing setups aren't lost.
const LS_KEYS = { loan: "prefectos_loan_boxes", account: "prefectos_account_boxes" };
const ACTIVE = ["starting", "running"];

const STREAM_EVENTS = [
  "job_started", "phase_changed", "agent_spawned", "agent_state", "plan_ready",
  "doc_started", "doc_completed", "eligibility_started", "policy_retrieved",
  "job_completed", "job_failed", "job_cancelled", "stream_end", "heartbeat",
];

export const isActive = (status) => ACTIVE.includes(status);

const emptyBox = (loanType) => ({
  loanType,
  label: "",
  inputPath: "",
  outputPath: "",
  prompt: "",
  defaultPrompt: "",
  promptEdited: false,
  jobId: null,
  status: "idle", // idle | starting | running | completed | failed | cancelled
  phase: "",      // documents | assessment | finished
  done: 0,
  total: 0,
  failed: 0,
  tokensIn: 0,
  tokensOut: 0,
  costUsd: null,   // list-price cost; null when the model has no published rate
  elapsedS: 0,     // server-reported elapsed at elapsedAt
  elapsedAt: 0,    // client clock when elapsedS arrived, so the card can tick
  currentDoc: "",
  decision: "",
  error: "",
  docs: [],
  mode: "deterministic", // deterministic (parse first, escalate failures) | ai_first
  docsClean: 0,   // reconciled in code, zero tokens
  docsEscalated: 0,
  aiShare: null,
  agents: [],     // the job's two agents: planner + processor
  plan: null,     // the Planning Agent's plan
  runFolder: "",  // date-stamped folder this run wrote into
  runDir: "",
  scan: null,     // {count, files, skipped} from /loan/scan
  reattached: false, // picked up from a previous page load rather than started here
  usePolicy: false,  // retrieve the bank's credit policy for this box
  policyCitations: [], // clauses the last run actually cited
});

/* ── one record per domain, held for the life of the tab ─────────────────── */

const domains = {};

function domainState(domain) {
  if (!domains[domain]) {
    domains[domain] = {
      snapshot: {
        boxes: {},
        config: { loanTypes: [], model: "", provider: "", pricing: null },
        configError: "",
      },
      listeners: new Set(),
      sources: {},      // loanType -> EventSource, deliberately not closed on unmount
      configState: "",  // "" | loading | loaded
    };
  }
  return domains[domain];
}

function setState(domain, updater) {
  const d = domainState(domain);
  const next = updater(d.snapshot);
  if (next === d.snapshot) return;
  d.snapshot = next;
  d.listeners.forEach((fn) => fn());
}

export function subscribe(domain, fn) {
  const d = domainState(domain);
  d.listeners.add(fn);
  return () => d.listeners.delete(fn);
}

export function getSnapshot(domain) {
  return domainState(domain).snapshot;
}

/* ── persistence: paths, edited prompts, and any in-flight job id ─────────── */

function loadPersisted(domain) {
  try {
    return JSON.parse(localStorage.getItem(LS_KEYS[domain]) || "{}");
  } catch {
    return {};
  }
}

function persist(domain, boxes) {
  const slim = {};
  Object.entries(boxes).forEach(([k, b]) => {
    slim[k] = {
      inputPath: b.inputPath,
      outputPath: b.outputPath,
      ...(b.promptEdited ? { prompt: b.prompt, promptEdited: true } : {}),
      ...(b.usePolicy ? { usePolicy: true } : {}),
      // Only running jobs are worth chasing after a reload; a finished one has
      // its report on disk and would just resurrect stale numbers.
      ...(b.jobId && isActive(b.status) ? { jobId: b.jobId, status: b.status } : {}),
    };
  });
  try {
    localStorage.setItem(LS_KEYS[domain], JSON.stringify(slim));
  } catch {
    /* storage full or disabled — configuration just won't survive a reload */
  }
}

function patch(domain, loanType, changes) {
  setState(domain, (s) => {
    const boxes = {
      ...s.boxes,
      [loanType]: { ...(s.boxes[loanType] || emptyBox(loanType)), ...changes },
    };
    persist(domain, boxes);
    return { ...s, boxes };
  });
}

// The institution is owned by the landing page (Settings dialog) and named in
// every report. One value for the whole app, so it lives outside the domains.
let bankName = "";
export function setBankName(name) {
  bankName = name || "";
}

// The credit-policy pack, likewise one per workspace. A box only uses it when
// its own "Cite policy" toggle is on.
let policyPath = "";
export function setPolicyPath(path) {
  policyPath = path || "";
}
export function getPolicyPath() {
  return policyPath;
}

/* ── streams ─────────────────────────────────────────────────────────────── */

function closeStream(domain, loanType) {
  const d = domainState(domain);
  const src = d.sources[loanType];
  if (src) {
    src.close();
    delete d.sources[loanType];
  }
}

/** Map a /loan/jobs/<id> snapshot onto a box — used when re-attaching. */
function applyJobSnapshot(domain, loanType, s) {
  patch(domain, loanType, {
    jobId: s.job_id,
    status: s.status,
    phase: s.phase || "",
    done: s.done ?? 0,
    total: s.total ?? 0,
    failed: s.failed ?? 0,
    tokensIn: s.tokens_in ?? 0,
    tokensOut: s.tokens_out ?? 0,
    costUsd: s.cost_usd ?? null,
    elapsedS: s.elapsed_s ?? 0,
    elapsedAt: Date.now(),
    docsClean: s.docs_clean ?? 0,
    docsEscalated: s.docs_escalated ?? 0,
    aiShare: s.ai_share ?? null,
    decision: s.decision || "",
    error: s.error || "",
    docs: s.docs || [],
    agents: s.agents || [],
    plan: s.plan || null,
    mode: s.mode || "deterministic",
    runFolder: s.run_folder || "",
    runDir: s.run_dir || "",
    currentDoc: isActive(s.status) ? s.current_doc || "" : "",
  });
}

function handleEvent(domain, loanType, type, d) {
  // Keep a running commentary of the job for the orchestrator's event log.
  docLog.record(domain, loanType, type, d);

  switch (type) {
    case "job_started":
      patch(domain, loanType, {
        status: "running",
        phase: d.phase,
        total: d.total,
        done: 0,
        failed: 0,
        docs: d.docs || [],
        agents: [],
        plan: null,
        error: "",
      });
      break;
    case "phase_changed":
      patch(domain, loanType, { phase: d.phase });
      break;
    case "agent_spawned":
    case "agent_state":
      setState(domain, (s) => {
        const b = s.boxes[loanType];
        if (!b || !d.agent) return s;
        const agents = b.agents.some((a) => a.agent_id === d.agent.agent_id)
          ? b.agents.map((a) => (a.agent_id === d.agent.agent_id ? d.agent : a))
          : [...b.agents, d.agent];
        // Agent calls carry the job's running totals, so the planner's spend
        // shows up before the first document completes.
        const tokens =
          d.tokens_in == null
            ? {}
            : {
                tokensIn: d.tokens_in,
                tokensOut: d.tokens_out,
                costUsd: d.cost_usd ?? null,
                elapsedS: d.elapsed_s ?? 0,
                elapsedAt: Date.now(),
              };
        return { ...s, boxes: { ...s.boxes, [loanType]: { ...b, agents, ...tokens } } };
      });
      break;
    case "plan_ready":
      patch(domain, loanType, { plan: d.plan || null, ...(d.error ? { error: d.error } : {}) });
      break;
    case "doc_started":
      patch(domain, loanType, { currentDoc: d.name, phase: "documents" });
      break;
    case "doc_completed":
      patch(domain, loanType, {
        done: d.done,
        total: d.total,
        failed: d.failed,
        // Only when the event carries them: spreading `docs: undefined` would
        // erase the list the job reported at start.
        ...(d.docs ? { docs: d.docs } : {}),
        tokensIn: d.tokens_in,
        tokensOut: d.tokens_out,
        costUsd: d.cost_usd ?? null,
        elapsedS: d.elapsed_s ?? 0,
        elapsedAt: Date.now(),
      });
      break;
    case "eligibility_started":
      patch(domain, loanType, { phase: "assessment", currentDoc: "" });
      break;
    case "policy_retrieved":
      patch(domain, loanType, { policyCitations: d.citations || [] });
      break;
    case "job_completed":
    case "job_failed":
    case "job_cancelled":
      // How a job ended is only known here, in the client's own stream — the
      // ledger recorded its start server-side when it was submitted.
      recordActivity("document_job",
        `${d.status === "completed" ? "Completed" : d.status === "cancelled" ? "Cancelled" : "Failed"} ` +
        `${getSnapshot(domain).boxes[loanType]?.label || loanType}` +
        (d.decision ? ` · ${d.decision}` : ""),
        {
          job_id: d.job_id || getSnapshot(domain).boxes[loanType]?.jobId,
          status: d.status,
          decision: d.decision || null,
          documents: d.done ?? 0,
          failed: d.failed ?? 0,
          tokens: (d.tokens_in || 0) + (d.tokens_out || 0),
          cost_usd: d.cost_usd ?? null,
          elapsed_s: d.elapsed_s ?? null,
          run_folder: getSnapshot(domain).boxes[loanType]?.runFolder || null,
        });
      patch(domain, loanType, {
        status: d.status,
        phase: "finished",
        done: d.done,
        total: d.total,
        failed: d.failed,
        tokensIn: d.tokens_in,
        tokensOut: d.tokens_out,
        costUsd: d.cost_usd ?? null,
        elapsedS: d.elapsed_s ?? 0,
        elapsedAt: Date.now(),
        docsClean: d.docs_clean ?? 0,
        docsEscalated: d.docs_escalated ?? 0,
        aiShare: d.ai_share ?? null,
        decision: d.decision || "",
        error: d.error || "",
        currentDoc: "",
        docs: d.docs || [],
        agents: d.agents || [],
        plan: d.plan || null,
      });
      break;
    case "stream_end":
      closeStream(domain, loanType);
      break;
    default:
      break;
  }
}

function attachStream(domain, loanType, jobId) {
  closeStream(domain, loanType);
  const d = domainState(domain);
  const src = new EventSource(`/loan/stream/${jobId}`);
  d.sources[loanType] = src;

  STREAM_EVENTS.forEach((t) => {
    src.addEventListener(t, (e) => {
      try {
        handleEvent(domain, loanType, t, JSON.parse(e.data));
      } catch {
        /* ignore malformed event */
      }
    });
  });

  src.onerror = () => {
    if (src.readyState !== EventSource.CLOSED) return; // transient; the browser retries
    closeStream(domain, loanType);
    // The job itself keeps running server-side, so fall back to a status poll
    // rather than reporting a failure the operator can't act on.
    fetch(`/loan/jobs/${jobId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("gone"))))
      .then((s) => {
        applyJobSnapshot(domain, loanType, s);
        if (isActive(s.status)) attachStream(domain, loanType, jobId);
      })
      .catch(() => patch(domain, loanType, { status: "failed", error: "Lost the progress stream." }));
  };
}

/**
 * After a reload, pick a job back up: ask the server where it got to, then
 * either re-open its stream or record how it ended.
 */
function reattach(domain, loanType, jobId) {
  fetch(`/loan/jobs/${jobId}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error("gone"))))
    .then((s) => {
      applyJobSnapshot(domain, loanType, s);
      patch(domain, loanType, { reattached: true });
      docLog.note(domain, loanType,
        `Re-attached to job <span class="ht">${jobId}</span> · ${s.done ?? 0}/${s.total ?? 0} documents done`,
        "info");
      if (isActive(s.status)) attachStream(domain, loanType, jobId);
    })
    .catch(() => {
      // Server restarted, or the job is older than this process knows about.
      patch(domain, loanType, { jobId: null, status: "idle", phase: "" });
    });
}

/* ── config + seeding, once per domain per page load ──────────────────────── */

export function ensureConfig(domain) {
  const d = domainState(domain);
  if (d.configState) return;
  d.configState = "loading";

  fetch(`/loan/config?domain=${domain}`)
    .then((r) => r.json())
    .then((cfg) => {
      d.configState = "loaded";
      const saved = loadPersisted(domain);
      setState(domain, (s) => {
        const boxes = { ...s.boxes };
        (cfg.loan_types || []).forEach((t) => {
          const sv = saved[t.id] || {};
          // A job may already be live in this tab (config re-fetch, second
          // mount) — never overwrite running state with a fresh box.
          const existing = boxes[t.id];
          boxes[t.id] = {
            ...(existing || emptyBox(t.id)),
            label: t.label,
            icon: t.icon,
            defaultPrompt: t.default_prompt || "",
            ...(existing
              ? {}
              : {
                  mode: t.default_mode || "deterministic",
                  prompt: sv.promptEdited ? sv.prompt : t.default_prompt || "",
                  promptEdited: !!sv.promptEdited,
                  inputPath: sv.inputPath || "",
                  outputPath: sv.outputPath || "",
                  usePolicy: !!sv.usePolicy,
                  ...(sv.jobId && isActive(sv.status)
                    ? { jobId: sv.jobId, status: sv.status, phase: "" }
                    : {}),
                }),
          };
        });
        return {
          ...s,
          boxes,
          configError: "",
          config: {
            loanTypes: cfg.loan_types || [],
            model: cfg.model || "",
            provider: cfg.provider || "",
            pricing: cfg.pricing || null,
          },
        };
      });

      // Chase anything that was still running when the tab was last closed.
      (cfg.loan_types || []).forEach((t) => {
        const sv = saved[t.id];
        if (sv?.jobId && isActive(sv.status) && !d.sources[t.id]) {
          reattach(domain, t.id, sv.jobId);
        }
      });
    })
    .catch(() => {
      d.configState = ""; // allow a retry on the next mount
      setState(domain, (s) => ({
        ...s,
        configError: "Could not load processing configuration from the server.",
      }));
    });
}

/* ── actions ─────────────────────────────────────────────────────────────── */

export function setField(domain, loanType, key, value) {
  patch(domain, loanType, key === "prompt" ? { prompt: value, promptEdited: true } : { [key]: value });
}

export function resetPrompt(domain, loanType) {
  setState(domain, (s) => {
    const b = s.boxes[loanType];
    if (!b) return s;
    const boxes = { ...s.boxes, [loanType]: { ...b, prompt: b.defaultPrompt, promptEdited: false } };
    persist(domain, boxes);
    return { ...s, boxes };
  });
}

export async function scanInput(domain, loanType, path) {
  if (!path || !path.trim()) {
    patch(domain, loanType, { scan: null });
    return;
  }
  try {
    const res = await fetch(`/loan/scan?path=${encodeURIComponent(path)}`);
    const d = await res.json();
    patch(domain, loanType, res.ok
      ? { scan: d, error: "" }
      : { scan: null, error: d.detail || "Path not found." });
  } catch {
    patch(domain, loanType, { scan: null });
  }
}

export async function start(domain, loanType) {
  const box = getSnapshot(domain).boxes[loanType];
  if (!box || isActive(box.status)) return;

  // A new run starts a new commentary.
  docLog.reset(domain, loanType);
  docLog.note(domain, loanType,
    `Processing requested · <span class="ht">${box.label || loanType}</span>`, "info");

  patch(domain, loanType, {
    status: "starting",
    error: "",
    decision: "",
    done: 0,
    failed: 0,
    total: 0,
    tokensIn: 0,
    tokensOut: 0,
    costUsd: null,
    elapsedS: 0,
    elapsedAt: Date.now(),
    docsClean: 0,
    docsEscalated: 0,
    aiShare: null,
    currentDoc: "",
    agents: [],
    plan: null,
    reattached: false,
    policyCitations: [],
  });

  try {
    const res = await fetch("/loan/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        loan_type: loanType,
        input_path: box.inputPath,
        output_path: box.outputPath,
        prompt: box.prompt,
        mode: box.mode,
        bank_name: bankName,
        // Empty unless this box opted in AND a pack is configured — the server
        // then treats the run exactly as it would without the feature.
        policy_path: box.usePolicy ? policyPath : "",
      }),
    });
    const d = await res.json();
    if (!res.ok) throw new Error(d.detail || "Could not start processing.");

    patch(domain, loanType, {
      jobId: d.job_id,
      total: d.total,
      status: "running",
      runFolder: d.run_folder || "",
      runDir: d.run_dir || "",
    });
    attachStream(domain, loanType, d.job_id);
  } catch (e) {
    docLog.note(domain, loanType, `Could not start: <span class="hr">${e.message}</span>`, "error");
    patch(domain, loanType, { status: "failed", error: e.message });
  }
}

export async function cancel(domain, loanType) {
  const box = getSnapshot(domain).boxes[loanType];
  if (!box?.jobId) return;
  try {
    const res = await fetch(`/loan/cancel/${box.jobId}`, { method: "POST" });
    if (!res.ok) {
      const d = await res.json();
      patch(domain, loanType, { error: d.detail || "Could not cancel." });
    }
  } catch (e) {
    patch(domain, loanType, { error: e.message });
  }
}

/** Every box across every domain that is still running — for the nav badge. */
export function activeCount(domain) {
  return Object.values(getSnapshot(domain).boxes).filter((b) => isActive(b.status)).length;
}
