import { useEffect, useMemo, useState } from "react";

/**
 * DecisionLedger — tamper-evident audit trail viewer (Ledger tab).
 *
 * Reads GET /ledger/<run_id> (added in server.py) and renders the
 * hash-chained decision provenance for any past or live run.
 *
 * Verification happens twice, deliberately:
 *   1. Client sweep — recomputes every SHA-256 in the browser using the
 *      exact canonicalization from decision_ledger.py:
 *          entry_hash = SHA256(json.dumps(entry - entry_hash,
 *                              sort_keys=True, separators=(",",":"),
 *                              ensure_ascii=False))
 *      Animated link-by-link: the demo moment for governance buyers.
 *   2. Server check — GET /ledger/<run_id>/verify runs the authoritative
 *      Python verify_file(). Shown as an independent attestation chip.
 */

const GENESIS = "0".repeat(64);

/* ── canonicalization: must mirror decision_ledger._canonical exactly ──── */

function canonical(v) {
  if (v === null || v === undefined) return "null";
  const t = typeof v;
  if (t === "number" || t === "boolean") return JSON.stringify(v);
  if (t === "string") return JSON.stringify(v); // JS & Python escape the same set with ensure_ascii=False
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  return (
    "{" +
    Object.keys(v)
      .sort()
      .map((k) => JSON.stringify(k) + ":" + canonical(v[k]))
      .join(",") +
    "}"
  );
}

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function computeEntryHash(entry) {
  const { entry_hash, ...rest } = entry;
  return sha256Hex(canonical(rest));
}

/* ── presentation helpers ──────────────────────────────────────────────── */

const short = (h) => (h ? h.slice(0, 10) + "…" + h.slice(-8) : "—");

const EVENT_META = {
  run_started:    { label: "RUN STARTED",    tone: "blue"   },
  run_completed:  { label: "RUN COMPLETED",  tone: "green"  },
  gate_presented: { label: "GATE PRESENTED", tone: "amber"  },
  gate_decision:  { label: "GATE DECISION",  tone: "purple" },
  agent_spawn:    { label: "AGENT SPAWN",    tone: "teal"   },
};
const metaFor = (ev) => EVENT_META[ev] || { label: (ev || "event").replaceAll("_", " ").toUpperCase(), tone: "dim" };

// Fields already shown in the summary row / headline — hidden from the detail grid
const CORE_KEYS = new Set(["seq", "ts", "event", "prev_hash", "entry_hash"]);

function headline(e) {
  switch (e.event) {
    case "run_started":    return e.activity || e.thread_id || "";
    case "gate_presented": return `${e.gate}${e.editable ? " · editable" : ""}${e.artifact_chars ? ` · artifact ${e.artifact_chars} chars` : ""}`;
    case "gate_decision":  return `${e.gate} → ${String(e.decision || "").toUpperCase()}${e.approver ? ` by ${e.approver}` : ""}${e.edited ? " (edited)" : ""}`;
    case "agent_spawn":    return `${e.agent_id} · ${e.stage} · ${e.model} (${e.provider})${e.skills?.length ? ` · skills: ${e.skills.join(", ")}` : ""}`;
    default: {
      const extras = Object.keys(e).filter((k) => !CORE_KEYS.has(k)).slice(0, 3);
      return extras.map((k) => `${k}: ${JSON.stringify(e[k])}`).join(" · ");
    }
  }
}

const fmtTs = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

/* ── component ─────────────────────────────────────────────────────────── */

export default function DecisionLedger() {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [ledger, setLedger] = useState(null);      // {run_id, project_id, entries, detail?}
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [verify, setVerify] = useState({});        // seq → ok | bad | pending
  const [chain, setChain] = useState("unverified"); // unverified | verifying | verified | tampered
  const [firstBad, setFirstBad] = useState(null);
  const [server, setServer] = useState(null);      // {ok, checked, error} | null
  const [eventFilter, setEventFilter] = useState("all");
  const [gatesOnly, setGatesOnly] = useState(false);
  const [openSeq, setOpenSeq] = useState(null);

  /* run list — newest first */
  useEffect(() => {
    fetch("/runs")
      .then((r) => r.json())
      .then((d) => {
        const list = (d.runs || []).slice().reverse();
        setRuns(list);
        if (list.length && !runId) setRunId(list[0].project_id);
      })
      .catch(() => setError("Could not load run list — is server.py running?"));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* ledger for the selected run */
  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    setLedger(null); setVerify({}); setChain("unverified"); setServer(null);
    setFirstBad(null); setOpenSeq(null); setError("");
    fetch(`/ledger/${encodeURIComponent(runId)}`)
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => (ok ? setLedger(d) : setError(d.detail || "Ledger unavailable.")))
      .catch(() => setError("Ledger request failed."))
      .finally(() => setLoading(false));
  }, [runId]);

  const entries = ledger?.entries || [];

  /* client-side sweep, link by link */
  async function runClientVerify() {
    setChain("verifying"); setFirstBad(null);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const results = {};
    let prev = GENESIS, expectedSeq = 1, broken = false;
    for (const e of entries) {
      results[e.seq] = "pending"; setVerify({ ...results });
      if (!reduced) await new Promise((r) => setTimeout(r, Math.max(30, 900 / entries.length)));
      const recomputed = await computeEntryHash(e);
      const ok = !broken && e.seq === expectedSeq && e.prev_hash === prev && recomputed === e.entry_hash;
      if (!ok && !broken) { broken = true; setFirstBad(e.seq); }
      results[e.seq] = ok ? "ok" : "bad"; setVerify({ ...results });
      prev = e.entry_hash; expectedSeq = e.seq + 1;
    }
    setChain(broken ? "tampered" : "verified");
  }

  async function runServerVerify() {
    setServer({ pending: true });
    try {
      const r = await fetch(`/ledger/${encodeURIComponent(runId)}/verify`);
      setServer(await r.json());
    } catch {
      setServer({ ok: false, checked: 0, error: "verify request failed" });
    }
  }

  const eventTypes = useMemo(() => ["all", ...new Set(entries.map((e) => e.event))], [entries]);
  const visible = entries.filter(
    (e) =>
      (eventFilter === "all" || e.event === eventFilter) &&
      (!gatesOnly || e.event === "gate_presented" || e.event === "gate_decision")
  );
  const gateDecisions = entries.filter((e) => e.event === "gate_decision").length;
  const spawns = entries.filter((e) => e.event === "agent_spawn").length;

  return (
    <div id="tab-ledger">
      {/* header row: run picker + seal + actions */}
      <div className="dl-head">
        <div className="dl-pick">
          <label className="dl-label" htmlFor="dl-run">Run</label>
          <select id="dl-run" value={runId} onChange={(e) => setRunId(e.target.value)}>
            {!runs.length && <option value="">No runs found</option>}
            {runs.map((r) => (
              <option key={r.project_id} value={r.project_id}>
                {r.project_id} — {(r.activity || "").slice(0, 60)}
              </option>
            ))}
          </select>
        </div>

        <div className="dl-actions">
          <span className={`dl-seal dl-seal-${chain}`}>
            <span className="dl-seal-dot" />
            {chain === "unverified" && "UNVERIFIED"}
            {chain === "verifying" && "AUDITING…"}
            {chain === "verified" && "CHAIN INTACT"}
            {chain === "tampered" && `TAMPERED @ #${firstBad}`}
          </span>
          <button className="dl-btn dl-btn-primary" disabled={!entries.length || chain === "verifying"} onClick={runClientVerify}>
            Verify chain
          </button>
          <button className="dl-btn" disabled={!entries.length || server?.pending} onClick={runServerVerify}>
            Server check
          </button>
          {server && !server.pending && (
            <span className={"dl-server " + (server.ok ? "ok" : "bad")}>
              server: {server.ok ? `intact (${server.checked})` : server.error || "broken"}
            </span>
          )}
        </div>
      </div>

      {/* stats + filters */}
      <div className="dl-bar">
        <div className="dl-stats">
          <span><b>{entries.length}</b> entries</span>
          <span><b>{gateDecisions}</b> gate decisions</span>
          <span><b>{spawns}</b> agent spawns</span>
          {ledger?.parse_errors > 0 && <span className="dl-warn">{ledger.parse_errors} unreadable lines</span>}
        </div>
        <div className="dl-filters">
          <select value={eventFilter} onChange={(e) => setEventFilter(e.target.value)}>
            {eventTypes.map((t) => <option key={t} value={t}>{t === "all" ? "All events" : t}</option>)}
          </select>
          <label className="dl-check">
            <input type="checkbox" checked={gatesOnly} onChange={(e) => setGatesOnly(e.target.checked)} />
            HITL gates only
          </label>
        </div>
      </div>

      {/* body */}
      {loading && <div className="dl-empty">Loading ledger…</div>}
      {!loading && error && <div className="dl-empty dl-error">{error}</div>}
      {!loading && !error && ledger && !entries.length && (
        <div className="dl-empty">{ledger.detail || "This run has no ledger entries."}</div>
      )}

      <ol className="dl-chain">
        {visible.map((e, i) => {
          const v = verify[e.seq];
          const m = metaFor(e.event);
          const open = openSeq === e.seq;
          const extraKeys = Object.keys(e).filter((k) => !CORE_KEYS.has(k));
          return (
            <li key={e.seq} className="dl-node">
              {i > 0 && (
                <div className={"dl-link" + (v === "ok" ? " ok" : v === "bad" ? " bad" : "")}>
                  <span className="dl-link-hash">{short(e.prev_hash)}</span>
                </div>
              )}
              <div
                className={"dl-card" + (v === "bad" ? " bad" : "") + (open ? " open" : "")}
                role="button" tabIndex={0} aria-expanded={open}
                onClick={() => setOpenSeq(open ? null : e.seq)}
                onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpenSeq(open ? null : e.seq); } }}
              >
                <div className="dl-row">
                  <span className="dl-seq">#{String(e.seq).padStart(3, "0")}</span>
                  <span className={"dl-event t-" + m.tone}>{m.label}</span>
                  {e.event === "gate_decision" && (
                    <span className={"dl-decision " + (e.decision === "approve" ? "ok" : "bad")}>
                      {String(e.decision || "").toUpperCase()}
                    </span>
                  )}
                  <span className="dl-ts">{fmtTs(e.ts)}</span>
                  {v === "ok" && <span className="dl-mark ok" title="Hash verified">✓</span>}
                  {v === "bad" && <span className="dl-mark bad" title="Hash mismatch">✕</span>}
                  {v === "pending" && <span className="dl-mark pend">…</span>}
                </div>
                <div className="dl-headline">{headline(e)}</div>
                {open && (
                  <div className="dl-detail" onClick={(ev) => ev.stopPropagation()}>
                    {extraKeys.map((k) => (
                      <div key={k}><span className="k">{k}</span><span className="v">{typeof e[k] === "string" ? e[k] : JSON.stringify(e[k])}</span></div>
                    ))}
                    <div><span className="k">prev_hash</span><span className="v">{e.prev_hash}</span></div>
                    <div><span className="k">entry_hash</span><span className="v">{e.entry_hash}</span></div>
                    {v === "bad" && (
                      <div className="dl-tampered-note">
                        Recomputed hash does not match the sealed record — this entry or an
                        upstream one was altered, inserted, removed, or reordered after signing.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {!loading && entries.length > 0 && !visible.length && (
        <div className="dl-empty">No entries match the current filters.</div>
      )}
    </div>
  );
}
