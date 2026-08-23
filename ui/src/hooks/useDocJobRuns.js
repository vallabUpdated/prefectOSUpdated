import { useEffect, useState } from "react";
import { subscribe as subscribeStore, getSnapshot, ensureConfig, isActive } from "../loanJobStore.js";
import { subscribe as subscribeLog, getLog, PHASE_LABEL } from "../docJobLog.js";

/**
 * useDocJobRuns — document processing jobs, shaped like pipeline runs.
 *
 * The orchestrator's Live run strip shows one chip per run. Document jobs are
 * runs too — same agents, same tokens, same commentary — they just live in
 * loanJobStore instead of usePipelineRun. This adapts them into the shape the
 * run switcher and the detail panes already understand, so both kinds of work
 * appear side by side.
 */
const DOMAINS = ["loan", "account"];

// Job status → the vocabulary the orchestrator's chips and dots use.
const STATUS = {
  starting: "starting",
  running: "running",
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
};

// The phases a document job moves through, in order, for the progress strip.
export const DOC_PHASES = [
  { key: "scanning", name: "Scanning", sub: "documents in the input folder" },
  { key: "planning", name: "Planning", sub: "PLANNING_AGENT · classify & route" },
  { key: "documents", name: "Documents", sub: "PROCESSING_AGENT · read & extract" },
  { key: "assessment", name: "Assessment", sub: "eligibility & compliance report" },
  { key: "finished", name: "Report", sub: "written to the output folder" },
];

// Phases the server emits that map onto one of the strip's rows.
const PHASE_ALIAS = { extracting: "documents", exceptions: "documents" };

const normPhase = (p) => PHASE_ALIAS[p] || p || "scanning";

function stagesFor(box) {
  const current = normPhase(box.phase);
  const idx = DOC_PHASES.findIndex((p) => p.key === current);
  const done = box.status === "completed";
  const stages = {};
  DOC_PHASES.forEach((p, i) => {
    if (done) stages[p.key] = "done";
    else if (idx < 0) stages[p.key] = "";
    else if (i < idx) stages[p.key] = "done";
    else if (i === idx) stages[p.key] = box.status === "failed" ? "failed" : "active";
    else stages[p.key] = "";
  });
  return stages;
}

/** The job's agents, keyed and renamed for AgentGrid. */
function agentsFor(box) {
  const out = {};
  (box.agents || []).forEach((a, i) => {
    out[a.agent_id || `AGENT_${i + 1}`] = {
      slot: i + 1,
      stage: a.role || "",
      model: a.model || "",
      status: a.status === "alive" ? "ALIVE" : a.status === "torn_down" ? "TORN_DOWN" : "PENDING",
      input_tokens: a.tokens_in || 0,
      output_tokens: a.tokens_out || 0,
      calls: a.calls || 0,
      card: a.card || "",
      label: a.label || "",
    };
  });
  return out;
}

function statusTextFor(box) {
  if (box.status === "starting") return "starting…";
  if (box.status === "running") {
    const phase = normPhase(box.phase);
    if (phase === "documents" && box.total) return `documents ${box.done}/${box.total}`;
    return (PHASE_LABEL[phase] || phase).toLowerCase();
  }
  return box.status;
}

function toRun(domain, box) {
  return {
    kind: "doc",
    // `doc_` prefix, not `doc:` — callers identify a document run by that
    // prefix before deciding which pane to open.
    runId: `doc_${domain}_${box.loanType}`,
    domain,
    loanType: box.loanType,
    jobId: box.jobId,
    chipName: box.label || box.loanType,
    activity: `${box.label || box.loanType} · ${box.inputPath || "no input folder"}`,
    status: STATUS[box.status] || box.status,
    statusText: statusTextFor(box),
    paused: false,
    approval: null,
    stages: stagesFor(box),
    phase: normPhase(box.phase),
    agents: agentsFor(box),
    tokIn: box.tokensIn || 0,
    tokOut: box.tokensOut || 0,
    costUsd: box.costUsd ?? null,
    elapsedS: box.elapsedS || 0,
    log: getLog(domain, box.loanType),
    docs: box.docs || [],
    done: box.done || 0,
    total: box.total || 0,
    failed: box.failed || 0,
    decision: box.decision || "",
    error: box.error || "",
    mode: box.mode,
    inputPath: box.inputPath || "",
    outputPath: box.outputPath || "",
    runFolder: box.runFolder || "",
    plan: box.plan || null,
    policyCitations: box.policyCitations || [],
    // Same fact under both names — `active` reads well next to the other run
    // fields, `running` is what callers ask for.
    active: isActive(box.status),
    running: isActive(box.status),
  };
}

export default function useDocJobRuns() {
  const [, bump] = useState(0);

  useEffect(() => {
    // Also makes sure the boxes exist and any job left running server-side is
    // picked back up, so the orchestrator finds jobs even when this session
    // never opened the processing window.
    DOMAINS.forEach(ensureConfig);

    const rerender = () => bump((n) => n + 1);
    const off = [...DOMAINS.map((d) => subscribeStore(d, rerender)), subscribeLog(rerender)];
    return () => off.forEach((fn) => fn());
  }, []);

  // Only boxes that have actually run — an idle box is configuration, not a run.
  return DOMAINS.flatMap((domain) =>
    Object.values(getSnapshot(domain).boxes)
      .filter((b) => b.jobId || b.status === "starting")
      .map((b) => toRun(domain, b))
  );
}
