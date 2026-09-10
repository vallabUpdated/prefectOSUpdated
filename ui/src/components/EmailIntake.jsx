import { useEffect, useState } from "react";
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
  kyc: "Account Processing · KYC",
  statement: "Account Processing · Statement",
  general: "Batch Ingest · General",
};

export default function EmailIntake({ approver = "system-admin" }) {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

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
    fetch(`${API}/email/intake/${id}`).then((r) => r.json()).then(setSel);

  const processDocs = async () => {
    setBusy(true); setErr("");
    try {
      const r = await fetch(
        `${API}/email/intake/${sel.intake_id}/process?approver=${encodeURIComponent(approver)}`,
        { method: "POST" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      setSel({ ...sel, status: "processed", batch_id: d.batch_id, queue: d.queue });
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

          {err && <div className="ei-err">{err}</div>}

          {sel.status === "pending" ? (
            <div className="ei-actions">
              <div className="ei-queue">
                Will be sent to <b>{QUEUE_LABEL[queue] || queue}</b> queue
                as <code>{sel.client_id}::{queue}</code>
              </div>
              <button className="ei-discard" disabled={busy} onClick={discard}>Discard</button>
              <button className="ei-process" disabled={busy} onClick={processDocs}>
                {busy ? "Submitting…" : `Process ${sel.documents.length} documents →`}
              </button>
            </div>
          ) : (
            <div className="ei-done">
              {sel.status === "processed"
                ? <>Processed to <b>{QUEUE_LABEL[sel.queue] || sel.queue}</b>{sel.batch_id ? <> · batch <code>{sel.batch_id}</code></> : null}</>
                : "Discarded"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
