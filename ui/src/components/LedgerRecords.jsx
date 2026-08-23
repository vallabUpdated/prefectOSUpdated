import { useCallback, useEffect, useState } from "react";
import { load, exportUrl, hasKey } from "../activityLedger.js";
import "../styles_ledger.css";

/**
 * LedgerRecords — what this access key has done, day by day.
 *
 * One row per activity, grouped under the day it happened, newest first, with
 * that day's totals. The ledger belongs to the key that is signed in: sign in
 * with a different key and you see that licensee's record, not this one's.
 */
const KIND_LABEL = {
  login: "Sign-in",
  logout: "Sign-out",
  document_job: "Document job",
  chat: "Policy question",
  pipeline_run: "Pipeline run",
  approval: "Approval",
  policy_index: "Policy index",
  other: "Activity",
};

const FILTERS = [
  ["", "All activity"],
  ["document_job", "Document jobs"],
  ["chat", "Policy questions"],
  ["pipeline_run", "Pipeline runs"],
  ["login", "Sign-ins"],
];

const money = (n) => (n == null ? null : `$${Number(n).toFixed(4)}`);

function dayLabel(day) {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (day === today) return "Today";
  if (day === yesterday) return "Yesterday";
  try {
    return new Date(day + "T00:00:00").toLocaleDateString(undefined, {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
  } catch {
    return day;
  }
}

function Detail({ d }) {
  const bits = [];
  if (d.documents) bits.push(`${d.documents} document${d.documents === 1 ? "" : "s"}`);
  if (d.decision) bits.push(d.decision);
  if (d.citations) bits.push(`${d.citations} citation${d.citations === 1 ? "" : "s"}`);
  if (d.tokens) bits.push(`${Number(d.tokens).toLocaleString()} tokens`);
  if (d.cost_usd) bits.push(money(d.cost_usd));
  if (d.elapsed_s) bits.push(`${d.elapsed_s}s`);
  if (d.run_folder) bits.push(d.run_folder);
  if (d.model) bits.push(d.model);
  if (!bits.length) return null;
  return <span className="lr-detail">{bits.join(" · ")}</span>;
}

export default function LedgerRecords() {
  const [data, setData] = useState(null);
  const [kind, setKind] = useState("");
  const [loading, setLoading] = useState(false);
  const [collapsed, setCollapsed] = useState({});

  const refresh = useCallback(() => {
    setLoading(true);
    load(kind)
      .then(setData)
      .catch(() => setData({ days: [], totals: { records: 0 }, owner: {} }))
      .finally(() => setLoading(false));
  }, [kind]);

  useEffect(refresh, [refresh]);

  const owner = data?.owner || {};
  const totals = data?.totals || { records: 0 };

  return (
    <div className="lr-page">
      <header className="lr-hero">
        <div className="lr-head">
          <div>
            <div className="lr-title-row">
              <h1 className="lr-title">Ledger Records</h1>
              <span className="lr-tag">Per access key</span>
            </div>
            <p className="lr-sub">
              Every activity performed with this access key, in the order it
              happened. Records are appended, never edited or removed.
              {owner.key_last4 ? ` Key ····${owner.key_last4}` : ""}
              {owner.user_name ? ` · ${owner.user_name}` : ""}
              {owner.institution ? ` · ${owner.institution}` : ""}
            </p>
          </div>
          <div className="lr-head-actions">
            <button className="lr-btn" onClick={refresh} disabled={loading}>
              {loading ? "Loading…" : "↻ Refresh"}
            </button>
            {hasKey() && totals.records > 0 && (
              <a className="lr-btn" href={exportUrl()} download>⬇ Export</a>
            )}
          </div>
        </div>

        <div className="lr-stats">
          <div className="lr-stat">
            <span className="lr-stat-val">{(totals.records || 0).toLocaleString()}</span>
            <span className="lr-stat-lbl">Records</span>
          </div>
          <div className="lr-stat">
            <span className="lr-stat-val">{(data?.days || []).length}</span>
            <span className="lr-stat-lbl">Days with activity</span>
          </div>
          <div className="lr-stat">
            <span className="lr-stat-val">{(totals.documents || 0).toLocaleString()}</span>
            <span className="lr-stat-lbl">Documents processed</span>
          </div>
          <div className="lr-stat">
            <span className="lr-stat-val">{(totals.tokens || 0).toLocaleString()}</span>
            <span className="lr-stat-lbl">Tokens</span>
          </div>
          <div className="lr-stat">
            <span className="lr-stat-val">{money(totals.cost_usd) || "$0.0000"}</span>
            <span className="lr-stat-lbl">Billed cost</span>
          </div>
        </div>
      </header>

      <div className="lr-filters">
        {FILTERS.map(([id, label]) => (
          <button
            key={id || "all"}
            className={"lr-filter" + (kind === id ? " active" : "")}
            onClick={() => setKind(id)}
          >
            {label}
            {totals.by_kind && id && totals.by_kind[id] ? ` (${totals.by_kind[id]})` : ""}
          </button>
        ))}
      </div>

      {!hasKey() && (
        <div className="lr-empty">
          Sign in with your access key to see its ledger. Activity is recorded
          against the key that performed it.
        </div>
      )}

      {hasKey() && !loading && (data?.days || []).length === 0 && (
        <div className="lr-empty">
          No activity recorded for this key yet. Process a document set or ask
          the policy a question and it will appear here.
        </div>
      )}

      {(data?.days || []).map((d) => {
        const shut = collapsed[d.day];
        return (
          <section className="lr-day" key={d.day}>
            <button
              className="lr-day-head"
              onClick={() => setCollapsed((c) => ({ ...c, [d.day]: !c[d.day] }))}
            >
              <span className="lr-day-caret">{shut ? "▸" : "▾"}</span>
              <span className="lr-day-name">{dayLabel(d.day)}</span>
              <span className="lr-day-date">{d.day}</span>
              <span className="lr-day-totals">
                {d.totals.records} record{d.totals.records === 1 ? "" : "s"}
                {d.totals.documents ? ` · ${d.totals.documents} docs` : ""}
                {d.totals.tokens ? ` · ${d.totals.tokens.toLocaleString()} tokens` : ""}
                {d.totals.cost_usd ? ` · ${money(d.totals.cost_usd)}` : ""}
              </span>
            </button>

            {!shut && (
              <div className="lr-rows">
                {d.records.map((r, i) => (
                  <div className={"lr-row " + r.kind} key={r.ts + i}>
                    <span className="lr-time">{r.ts.slice(11, 19)}</span>
                    <span className={"lr-kind " + r.kind}>{KIND_LABEL[r.kind] || r.kind}</span>
                    <span className="lr-summary">
                      {r.summary}
                      <Detail d={r.details || {}} />
                    </span>
                    <span className="lr-who">{r.user_name}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
