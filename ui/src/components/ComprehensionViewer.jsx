import { useEffect, useMemo, useState } from "react";

/**
 * ComprehensionViewer — Stage 0 (Legacy Comprehension) results (Stage 0 tab).
 *
 * Reads GET /comprehension/<run_id> and shows, for runs that started from an
 * existing codebase:
 *   • the three comprehension documents the COMPREHENDER agent produced
 *     (architecture.md / business_rules.md / risk_register.md), rendered
 *     with a tiny dependency-free markdown renderer;
 *   • the governance provenance around them, straight from the decision
 *     ledger: what was digested (files seen/included, digest SHA-256),
 *     which credential files were withheld, what was RAG-indexed, and the
 *     two comprehender HITL gates with their decisions.
 */

/* ── tiny markdown-lite renderer (headings, lists, tables, code, bold) ─── */

function inline(text, keyBase) {
  // **bold**, `code` — split preserving order
  const parts = [];
  let rest = text, i = 0;
  const re = /(\*\*[^*]+\*\*|`[^`]+`)/;
  while (rest) {
    const m = rest.match(re);
    if (!m) { parts.push(rest); break; }
    if (m.index > 0) parts.push(rest.slice(0, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={`${keyBase}-b${i++}`}>{tok.slice(2, -2)}</strong>);
    else parts.push(<code key={`${keyBase}-c${i++}`} className="cv-code">{tok.slice(1, -1)}</code>);
    rest = rest.slice(m.index + tok.length);
  }
  return parts;
}

function renderMarkdown(md) {
  const out = [];
  const lines = (md || "").replace(/\r\n/g, "\n").split("\n");
  let i = 0, key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {                       // fenced code block
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++;
      out.push(<pre key={key++} className="cv-pre">{buf.join("\n")}</pre>);
      continue;
    }

    const h = line.match(/^(#{1,4})\s+(.*)/);           // headings
    if (h) {
      const Tag = `h${Math.min(h[1].length + 2, 6)}`;   // # → h3 … keeps app hierarchy
      out.push(<Tag key={key++} className={`cv-h cv-h${h[1].length}`}>{inline(h[2], key)}</Tag>);
      i++; continue;
    }

    if (/^\s*\|.*\|\s*$/.test(line)) {                  // pipe table
      const rows = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(rows[0]);
      const body = rows.slice(/^\s*\|[\s\-:|]+\|\s*$/.test(rows[1] || "") ? 2 : 1).map(cells);
      out.push(
        <table key={key++} className="cv-table">
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${key}h${j}`)}</th>)}</tr></thead>
          <tbody>{body.map((r, ri) => (
            <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${key}r${ri}c${j}`)}</td>)}</tr>
          ))}</tbody>
        </table>
      );
      continue;
    }

    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {             // list block
      const items = [];
      const ordered = /^\s*\d+\./.test(line);
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
      const L = ordered ? "ol" : "ul";
      out.push(
        <L key={key++} className="cv-list">
          {items.map((t, j) => <li key={j}>{inline(t, `${key}l${j}`)}</li>)}
        </L>
      );
      continue;
    }

    if (line.trim() === "") { i++; continue; }          // blank

    const buf = [line];                                  // paragraph
    i++;
    while (i < lines.length && lines[i].trim() !== "" &&
           !/^(#{1,4}\s|```|\s*\||\s*([-*]|\d+\.)\s)/.test(lines[i])) buf.push(lines[i++]);
    out.push(<p key={key++} className="cv-p">{inline(buf.join(" "), key)}</p>);
  }
  return out;
}

/* ── helpers ───────────────────────────────────────────────────────────── */

const DOCS = [
  ["architecture.md",   "Architecture"],
  ["business_rules.md", "Business rules"],
  ["risk_register.md",  "Risk register"],
];

const short = (h) => (h ? h.slice(0, 10) + "…" + h.slice(-8) : "—");
const fmtTs = (iso) => {
  const d = new Date(iso);
  return isNaN(d) ? iso || "" : d.toLocaleString(undefined, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

/* ── component ─────────────────────────────────────────────────────────── */

export default function ComprehensionViewer() {
  const [runs, setRuns] = useState([]);
  const [runId, setRunId] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [doc, setDoc] = useState("architecture.md");

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

  useEffect(() => {
    if (!runId) return;
    setLoading(true); setData(null); setError("");
    fetch(`/comprehension/${encodeURIComponent(runId)}`)
      .then((r) => r.json().then((d) => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (!ok) { setError(d.detail || "Comprehension data unavailable."); return; }
        setData(d);
        const first = DOCS.find(([f]) => d.documents?.[f]);
        setDoc(first ? first[0] : "architecture.md");
      })
      .catch(() => setError("Comprehension request failed."))
      .finally(() => setLoading(false));
  }, [runId]);

  const dg = data?.digested;
  const ix = data?.indexed;
  const decisions = useMemo(
    () => (data?.gates || []).filter((g) => g.event === "gate_decision"),
    [data]
  );

  return (
    <div id="tab-comprehension">
      {/* header: run picker */}
      <div className="cv-head">
        <div className="cv-pick">
          <label className="cv-label" htmlFor="cv-run">Run</label>
          <select id="cv-run" value={runId} onChange={(e) => setRunId(e.target.value)}>
            {!runs.length && <option value="">No runs found</option>}
            {runs.map((r) => (
              <option key={r.project_id} value={r.project_id}>
                {r.project_id} — {(r.activity || "").slice(0, 60)}
              </option>
            ))}
          </select>
        </div>
        {data?.has_stage0 && dg && (
          <span className="cv-badge">STAGE 0 · LEGACY COMPREHENSION</span>
        )}
      </div>

      {loading && <div className="cv-empty">Loading Stage 0 results…</div>}
      {!loading && error && <div className="cv-empty cv-error">{error}</div>}

      {!loading && data && !data.has_stage0 && (
        <div className="cv-empty">
          This run didn't start from an existing codebase — Stage 0 was skipped.
          <br />
          <span className="cv-hint">
            Start a run with a codebase path (Live run → Existing codebase) and the
            COMPREHENDER agent's analysis will appear here.
          </span>
        </div>
      )}

      {!loading && data?.has_stage0 && (
        <div className="cv-body">
          {/* ── provenance rail ─────────────────────────────────────────── */}
          <aside className="cv-rail">
            {dg && (
              <div className="cv-card">
                <div className="cv-card-title">What the agent saw</div>
                <div className="cv-kv"><span className="k">codebase</span><span className="v">{dg.codebase_path}</span></div>
                <div className="cv-kv"><span className="k">files seen</span><span className="v">{dg.files_seen}</span></div>
                <div className="cv-kv"><span className="k">files digested</span><span className="v">{dg.files_included}</span></div>
                <div className="cv-kv"><span className="k">digest sha-256</span><span className="v mono" title={dg.digest_sha256}>{short(dg.digest_sha256)}</span></div>
                <div className="cv-note">
                  The digest hash pins the exact input the COMPREHENDER analysed —
                  the analysis below is attributable to this input and nothing else.
                </div>
              </div>
            )}

            {dg?.secrets_withheld?.length > 0 && (
              <div className="cv-card cv-card-guard">
                <div className="cv-card-title">Credentials withheld</div>
                {dg.secrets_withheld.map((f) => (
                  <div key={f} className="cv-secret mono">{f}</div>
                ))}
                <div className="cv-note">
                  Files that look like credentials were excluded from the digest
                  and never reached a model.
                </div>
              </div>
            )}

            {ix && (
              <div className="cv-card">
                <div className="cv-card-title">Governed retrieval index</div>
                <div className="cv-kv"><span className="k">chunks added</span><span className="v">{ix.chunks_added}</span></div>
                <div className="cv-kv"><span className="k">total chunks</span><span className="v">{ix.total_chunks}</span></div>
                <div className="cv-kv"><span className="k">backend</span><span className="v">{ix.dense_backend}</span></div>
                <div className="cv-note">
                  Later stages retrieve exact modules from this index — the digest
                  is the overview, the index is the microscope.
                </div>
              </div>
            )}

            {decisions.length > 0 && (
              <div className="cv-card">
                <div className="cv-card-title">HITL gates</div>
                {decisions.map((g) => (
                  <div key={g.seq} className="cv-gate">
                    <span className={"cv-gate-dot " + (g.decision === "approve" ? "ok" : "bad")} />
                    <span className="cv-gate-name mono">{g.gate}</span>
                    <span className={"cv-gate-dec " + (g.decision === "approve" ? "ok" : "bad")}>
                      {String(g.decision || "").toUpperCase()}
                    </span>
                    <span className="cv-gate-ts">{fmtTs(g.ts)}{g.approver ? ` · ${g.approver}` : ""}</span>
                  </div>
                ))}
              </div>
            )}
          </aside>

          {/* ── documents ───────────────────────────────────────────────── */}
          <section className="cv-docs">
            <div className="cv-seg">
              {DOCS.map(([f, label]) => (
                <button
                  key={f}
                  className={doc === f ? "on" : ""}
                  disabled={!data.documents?.[f]}
                  onClick={() => setDoc(f)}
                >
                  {label}
                  {!data.documents?.[f] && <em> — none</em>}
                </button>
              ))}
            </div>
            <div className="cv-doc-body">
              {data.documents?.[doc]
                ? renderMarkdown(data.documents[doc])
                : <div className="cv-empty">The COMPREHENDER didn't produce this document for this run.</div>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
