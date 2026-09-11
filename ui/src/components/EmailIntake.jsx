import { useEffect, useRef, useState } from "react";
import { inr, usd, rateLabel } from "../money.js";
import "../styles_email.css";

/**
 * EmailIntake — human-in-the-loop review of emailed document packs.
 * Lists validated pending intakes (sender authenticated, docs template-
 * matched, set complete). The reviewer reads the email body, downloads
 * documents, then clicks "Process documents" — routed to the queue for
 * the pack's product — or discards with a reason.
 */
const API = "";   // same-origin; set base here if the API runs elsewhere

const QUEUE_LABEL = {
  home_loan: "Loan Processing · Home",
  vehicle_loan: "Loan Processing · Vehicle",
  personal_loan: "Loan Processing · Personal",
  mortgage: "Loan Processing · Mortgage",
  kyc: "Account Processing · KYC",
  statement: "Account Processing · Statement",
  general: "Account Processing · General",
};

const DECISION_CLASS = {
  ELIGIBLE: "ok", NOT_ELIGIBLE: "bad", NEEDS_REVIEW: "warn",
  COMPLETE: "ok", INCOMPLETE: "bad", REPORTED: "info",
};
const ACTIVE = ["queued", "running"];

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

/**
 * Processing result for one intake: live progress while the engine runs
 * (polls /loan/jobs/<id> every 2s), then the same Tokens / Cost / Time
 * meters as the loan cards, the decision, and the report links. Once the
 * engine has written summary.json the numbers come from the intake itself
 * (`result`), so they are still there after a server restart.
 */
function IntakeResult({ sel, fxRate }) {
  const [job, setJob] = useState(null);
  const [lost, setLost] = useState(false);
  const timer = useRef(null);
  const jobId = sel.job_id;
  const finalResult = sel.result;           // from summary.json, once written

  useEffect(() => {
    setJob(null); setLost(false);
    if (!jobId || (finalResult && !ACTIVE.includes(finalResult.status))) return undefined;
    let stop = false;
    const tick = () =>
      fetch(`/loan/jobs/${jobId}`)
        .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
        .then((j) => {
          if (stop) return;
          setJob(j);
          if (ACTIVE.includes(j.status)) timer.current = setTimeout(tick, 2000);
        })
        .catch(() => !stop && setLost(true));   // engine restarted: fall back to summary
    tick();
    return () => { stop = true; clearTimeout(timer.current); };
  }, [jobId, finalResult && finalResult.status]);

  const r = job || finalResult;
  if (!jobId) return null;
  if (!r) {
    return (
      <div className="ei-result">
        <div className="ei-label">Processing</div>
        <div className="es-note">
          {lost ? "Job details are no longer available from the engine and no report was written."
                : "Starting the processing engine…"}
        </div>
      </div>
    );
  }
  const active = ACTIVE.includes(r.status);
  const tokIn = r.tokens_in ?? 0, tokOut = r.tokens_out ?? 0;
  const done = r.done ?? 0, total = r.total ?? sel.documents.length;

  return (
    <div className="ei-result">
      <div className="ei-label">
        Processing · {sel.processing_label || sel.processing_type}
        {r.model ? <span className="ei-model"> · {r.model}</span> : null}
      </div>

      {active && (
        <div className="ei-progress">
          <div className="ei-progress-bar">
            <div className="ei-progress-fill" style={{ width: `${total ? (done / total) * 100 : 5}%` }} />
          </div>
          <span>{r.phase || r.status} · {done}/{total} documents{r.current_doc ? ` · ${r.current_doc}` : ""}</span>
        </div>
      )}

      <div className="lc-meters ei-meters">
        <div className="lc-meter meter-tokens">
          <div className="lc-meter-head"><span className="lc-meter-icon">⚡</span><span className="lc-meter-label">Tokens</span></div>
          <span className="lc-meter-value">{(tokIn + tokOut).toLocaleString()}</span>
          <span className="lc-meter-sub">
            <span className="lc-sub-pill">{tokIn.toLocaleString()} in</span>
            <span className="lc-sub-sep">·</span>
            <span className="lc-sub-pill">{tokOut.toLocaleString()} out</span>
          </span>
        </div>
        <div className="lc-meter meter-cost">
          <div className="lc-meter-head"><span className="lc-meter-icon">💳</span><span className="lc-meter-label">Cost</span></div>
          <span className="lc-meter-value strong">{inr(r.cost_usd, fxRate)}</span>
          <span className="lc-meter-sub" title={`Billed in USD; converted ${rateLabel(fxRate)}`}>
            <span className="lc-sub-tag">{usd(r.cost_usd)}</span>
            <span className="lc-sub-rate">{rateLabel(fxRate)}</span>
          </span>
        </div>
        <div className="lc-meter meter-time">
          <div className="lc-meter-head"><span className="lc-meter-icon">⏱️</span><span className="lc-meter-label">Time</span></div>
          <span className={"lc-meter-value" + (active ? " ticking" : "")}>{fmtDuration(r.elapsed_s)}</span>
          <span className="lc-meter-sub">
            <span className="lc-sub-tag">{done > 0 ? `${fmtDuration((r.elapsed_s || 0) / done)} / doc` : "elapsed"}</span>
          </span>
        </div>
      </div>

      {r.decision && (
        <div className={"lc-decision " + (DECISION_CLASS[r.decision] || "warn")}>
          {r.decision.replace(/_/g, " ")}
        </div>
      )}
      {r.status === "failed" && <div className="ei-err">Processing failed{r.error ? `: ${r.error}` : ""}</div>}
      {r.status !== "failed" && r.error && (
        <div className="ei-err">Completed with an error — {String(r.error).slice(0, 300)}</div>
      )}
      {r.status === "cancelled" && <div className="ei-err">Processing was cancelled.</div>}

      {r.status === "completed" && (
        <div className="ei-reports">
          <a className="lc-link-chip lc-link-chip-primary" target="_blank" rel="noreferrer"
             href={`${API}/email/intake/${sel.intake_id}/report?kind=html`}>📄 HTML Report</a>
          <a className="lc-link-chip" target="_blank" rel="noreferrer"
             href={`${API}/email/intake/${sel.intake_id}/report?kind=md`}>📝 Markdown</a>
          <a className="lc-link-chip" target="_blank" rel="noreferrer"
             href={`${API}/email/intake/${sel.intake_id}/report?kind=json`}>⚙️ JSON Data</a>
          {sel.run_folder && <span className="es-note" title={sel.run_dir}>Saved to <code>{sel.run_folder}</code></span>}
        </div>
      )}
    </div>
  );
}

export default function EmailIntake({ approver = "system-admin", fxRate, bankName = "" }) {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  // Prompt for THIS intake: starts as the configured prompt for the pack's
  // product type; edits stay local to the intake and are sent on process.
  const [prompt, setPrompt] = useState("");
  const [promptOpen, setPromptOpen] = useState(false);
  const promptRef = useRef(null);

  const refresh = () =>
    fetch(`${API}/email/intake`)
      .then((r) => r.json())
      .then((d) => setItems(d.intakes || []))
      .catch(() => setErr("Could not reach the email intake API"));

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);
    return () => clearInterval(t);
  }, []);

  const open = (id) =>
    fetch(`${API}/email/intake/${id}`).then((r) => r.json()).then((d) => {
      setSel(d);
      setPrompt(d.status === "pending" ? (d.default_prompt || "") : (d.prompt || d.default_prompt || ""));
      setPromptOpen(false);
      setErr("");
    });

  useEffect(() => {
    const el = promptRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(Math.max(el.scrollHeight, 160), 480) + "px";
  }, [promptOpen, prompt]);

  const canRun = !!sel && (sel.status === "pending"
    || (sel.status === "processed" && sel.engine === "loan"));
  const promptEdited = canRun && prompt.trim() !== (sel.default_prompt || "").trim();
  const runActive = !!sel && sel.status === "processed" && !!sel.run_active;
  const promptTooShort = promptEdited && prompt.trim().length > 0 && prompt.trim().length < 20;

  const processDocs = async () => {
    setBusy(true); setErr("");
    try {
      const qs = new URLSearchParams({ approver, bank_name: bankName || "" });
      if (sel.status === "processed") qs.set("rerun", "1");
      const r = await fetch(`${API}/email/intake/${sel.intake_id}/process?${qs}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // only an edited prompt travels; empty means "use the configured one"
        body: JSON.stringify({ prompt: promptEdited ? prompt : "" }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      // a re-run starts fresh: previous numbers/report must not linger
      const { result: _r, run_active: _a, ...rest } = sel;
      setSel({ ...rest, status: "processed", result: null, run_active: true, ...d,
               runs: sel.status === "processed"
                 ? [...(sel.runs || []), { job_id: sel.job_id, processed_at: sel.processed_at,
                                           processed_by: sel.processed_by, prompt_edited: sel.prompt_edited,
                                           result: sel.result }]
                 : (sel.runs || []) });
      refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };

  const discard = async () => {
    const reason = window.prompt("Rejection reason (min 10 characters):", "");
    if (!reason) return;
    setBusy(true); setErr("");
    try {
      const r = await fetch(
        `${API}/email/intake/${sel.intake_id}/discard?approver=${encodeURIComponent(approver)}&reason=${encodeURIComponent(reason)}`,
        { method: "POST" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      setSel({ ...sel, status: "discarded" });
      refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  };

  const queue = sel && (sel.product || "general");

  return (
    <div className="ei-wrap">
      <div className="ei-list">
        <div className="ei-list-head">
          <span>Email intake</span>
          <span className="ei-count">{items.filter(i => i.status === "pending").length} pending</span>
        </div>
        {items.length === 0 && <div className="ei-empty">No emailed document packs yet.</div>}
        {items.map((it) => (
          <button key={it.intake_id}
            className={"ei-row" + (sel?.intake_id === it.intake_id ? " sel" : "")}
            onClick={() => open(it.intake_id)}>
            <span className={"ei-dot " + it.status} />
            <span className="ei-row-main">
              <span className="ei-row-subj">{it.subject || "(no subject)"}</span>
              <span className="ei-row-meta">{it.sender} · {it.client_id}{it.product ? ` · ${it.product}` : ""} · {it.n_docs} docs</span>
            </span>
            <span className={"ei-status " + it.status}>{it.status}</span>
          </button>
        ))}
      </div>

      {sel && (
        <div className="ei-detail">
          <div className="ei-detail-head">
            <div>
              <div className="ei-subj">{sel.subject || "(no subject)"}</div>
              <div className="ei-from">From {sel.sender} · verified sender · {new Date(sel.received_at).toLocaleString()}</div>
            </div>
            <span className={"ei-status big " + sel.status}>{sel.status}</span>
          </div>

          <div className="ei-body">
            <div className="ei-label">Email body</div>
            <pre>{sel.body_text?.trim() || "(empty body)"}</pre>
          </div>

          <div className="ei-label">Validated documents · set complete for {sel.product || "general"}</div>
          <div className="ei-docs">
            {sel.documents.map((d) => (
              <div key={d.name} className="ei-doc">
                <span className="ei-doc-name">{d.name}</span>
                <span className="ei-doc-type">{d.doc_type || "unclassified"}</span>
                <span className="ei-doc-size">{(d.size / 1024).toFixed(0)} KB</span>
                <a className="ei-doc-dl" download={d.name}
                   href={`${API}/email/intake/${sel.intake_id}/documents/${encodeURIComponent(d.name)}`}>
                  Download
                </a>
              </div>
            ))}
          </div>

          {(canRun || sel.prompt) && (
            <div className="ei-prompt">
              <button type="button" className="ei-prompt-head" onClick={() => setPromptOpen(!promptOpen)}
                aria-expanded={promptOpen}>
                <span className="ei-label" style={{ margin: 0 }}>
                  Processing prompt · {sel.processing_label || QUEUE_LABEL[queue] || queue}
                </span>
                {canRun
                  ? (promptEdited ? <span className="es-pill warn">edited for this intake</span>
                                  : <span className="es-pill off">configured default</span>)
                  : (sel.prompt_edited ? <span className="es-pill warn">edited for this intake</span>
                                       : <span className="es-pill off">configured default</span>)}
                <span style={{ flex: 1 }} />
                {!promptOpen && <span className="ei-prompt-preview">{(prompt || "").split("\n")[0]}</span>}
                <span className="ei-prompt-chev">{promptOpen ? "▾" : "▸"}</span>
              </button>
              {promptOpen && (
                <div className="ei-prompt-body">
                  <textarea ref={promptRef} value={prompt} spellCheck={false}
                    readOnly={!canRun || runActive}
                    onChange={(e) => setPrompt(e.target.value)} />
                  <div className="ei-prompt-foot">
                    <span className="es-note">
                      {canRun && !runActive
                        ? (promptTooShort ? "At least 20 characters, or leave it as the default."
                          : sel.status === "processed"
                            ? "The prompt this intake was processed with. Change it and Process again to re-run; the earlier run is kept in the history below."
                            : "This is what the engine runs against. Edits apply to this intake only; change the default under Settings → Processing prompts.")
                        : "The prompt this intake was processed with."}
                    </span>
                    {canRun && !runActive && promptEdited && (
                      <button type="button" className="es-test"
                        onClick={() => setPrompt(sel.default_prompt || "")}>Reset to configured</button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {err && <div className="ei-err">{err}</div>}

          {sel.status === "pending" ? (
            <div className="ei-actions">
              <div className="ei-queue">
                Will run through <b>{QUEUE_LABEL[queue] || queue}</b> with the
                configured prompt for that type · workspace <code>{sel.client_id}</code>
              </div>
              <button className="ei-discard" disabled={busy} onClick={discard}>Discard</button>
              <button className="ei-process" disabled={busy || promptTooShort} onClick={processDocs}>
                {busy ? "Submitting…" : `Process ${sel.documents.length} documents →`}
              </button>
            </div>
          ) : (
            <div className="ei-done">
              {sel.status === "processed"
                ? (sel.engine === "loan"
                    ? <>Processed by <b>{QUEUE_LABEL[queue] || queue}</b>{sel.processed_by ? <> · approved by {sel.processed_by}</> : null}{sel.processed_at ? <> · {new Date(sel.processed_at).toLocaleString()}</> : null}{sel.policy_note ? <><br /><span style={{ color: "#b45309" }}>⚠ {sel.policy_note}</span></> : null}</>
                    : <>Processed to <b>{QUEUE_LABEL[sel.queue] || sel.queue}</b>{sel.batch_id ? <> · batch <code>{sel.batch_id}</code></> : null}</>)
                : "Discarded"}
            </div>
          )}
          {sel.status === "processed" && sel.engine === "loan" && (
            <IntakeResult sel={sel} fxRate={fxRate} />
          )}
          {sel.status === "processed" && sel.engine === "loan" && (
            <div className="ei-actions">
              <div className="ei-queue">
                {runActive
                  ? "Processing is in progress — wait for it to finish before running again."
                  : <>Run again through <b>{QUEUE_LABEL[queue] || queue}</b>{promptEdited ? " with the edited prompt" : " with the same prompt"} — the report above will be replaced; earlier runs stay in the history.</>}
              </div>
              <button className="ei-process" disabled={busy || runActive || promptTooShort} onClick={processDocs}>
                {busy ? "Submitting…" : "Process again ↻"}
              </button>
            </div>
          )}
          {!!(sel.runs && sel.runs.length) && (
            <div className="ei-runs">
              <div className="ei-label">Earlier runs ({sel.runs.length})</div>
              {sel.runs.slice().reverse().map((r, i) => (
                <div className="ei-run" key={r.job_id || i}>
                  <span className="ei-run-n">#{sel.runs.length - i}</span>
                  <span>{r.processed_at ? new Date(r.processed_at).toLocaleString() : "—"}</span>
                  <span className="ei-run-meta">{r.processed_by || ""}</span>
                  <span className={"es-pill " + (r.prompt_edited ? "warn" : "off")}>{r.prompt_edited ? "edited prompt" : "default prompt"}</span>
                  <span style={{ flex: 1 }} />
                  {r.result?.decision && (
                    <span className={"ei-run-decision " + (DECISION_CLASS[r.result.decision] || "warn")}>{r.result.decision.replace(/_/g, " ")}</span>
                  )}
                  {r.result && <span className="ei-run-meta">{((r.result.tokens_in || 0) + (r.result.tokens_out || 0)).toLocaleString()} tok · {usd(r.result.cost_usd)} · {fmtDuration(r.result.elapsed_s)}</span>}
                  {r.job_id && <a className="ei-run-link" href={`/loan/report/${r.job_id}?kind=html`} target="_blank" rel="noreferrer" title="Report from the engine's job cache (available until the engine restarts)">report</a>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
