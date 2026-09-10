import { useEffect, useState } from "react";
import "../styles_email.css";

/**
 * SettingsEmail — "valid email inboxes" configuration.
 * Shows the intake mailbox, the SPF/DKIM requirement toggle, and the
 * sender-route table (allowed senders → client → product). Saves via
 * PUT /email/settings; every save is sealed to the email audit chain
 * as routes_updated. The mailbox password is never shown or stored
 * here — it lives only in the EMAIL_INGEST_PASSWORD environment.
 */
export default function SettingsEmail({ approver = "system-admin", products = [] }) {
  const [cfg, setCfg] = useState(null);
  const [state, setState] = useState(null);   // {kind:"ok"|"bad", text}
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/email/settings").then((r) => r.json()).then(setCfg)
      .catch(() => setState({ kind: "bad", text: "Email intake API unreachable." }));
  }, []);

  if (!cfg) return <div className="es-section"><div className="es-title">Email intake</div>
    <div className="es-note">{state?.text || "Loading…"}</div></div>;

  const productOpts = products.length ? products
    : ["home_loan", "vehicle_loan", "personal_loan", "kyc", "statement"];

  const setRoute = (i, patch) => {
    const routes = cfg.routes.map((r, j) => (j === i ? { ...r, ...patch } : r));
    setCfg({ ...cfg, routes });
  };

  const save = async () => {
    setSaving(true); setState(null);
    try {
      const r = await fetch(`/email/settings?approver=${encodeURIComponent(approver)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      setState({ kind: "ok", text: "Saved and sealed — applies next poll." });
    } catch (e) { setState({ kind: "bad", text: String(e.message || e) }); }
    setSaving(false);
  };

  return (
    <div className="es-section">
      <div className="es-title">Email intake — valid inboxes</div>

      <div className="es-box">
        <span>Intake mailbox</span>
        <span className="es-mono">{cfg.imap_user}</span>
        <span className="es-mono">{cfg.imap_host}:{cfg.imap_port}</span>
        <label style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={!!cfg.require_authentication}
            onChange={(e) => setCfg({ ...cfg, require_authentication: e.target.checked })} />
          Require SPF/DKIM pass (anti-spoofing)
        </label>
      </div>

      <div className="es-table">
        {cfg.routes.map((r, i) => (
          <div className="es-tr" key={i}>
            <input value={r.senders.join(", ")}
              title="Allowed senders — exact addresses or *@domain, comma-separated"
              onChange={(e) => setRoute(i, {
                senders: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              })} />
            <input value={r.client_id} style={{ maxWidth: 150 }}
              title="Client workspace id"
              onChange={(e) => setRoute(i, { client_id: e.target.value })} />
            <select value={r.product || ""}
              onChange={(e) => setRoute(i, { product: e.target.value || null })}>
              <option value="">(no product)</option>
              {productOpts.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <button className="es-del" title="Remove route"
              onClick={() => setCfg({ ...cfg, routes: cfg.routes.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
        ))}
        <button className="es-add"
          onClick={() => setCfg({
            ...cfg,
            routes: [...cfg.routes, { client_id: "", product: null, senders: [] }],
          })}>
          + Add sender route
        </button>
      </div>

      <div className="es-row-actions">
        <span className="es-note">
          Mail from any address not listed is rejected and ledgered.
          Saves are sealed to the audit chain.
        </span>
        {state && <span className={state.kind === "ok" ? "es-ok" : "es-bad"}>{state.text}</span>}
        <button className="es-save" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save and seal"}
        </button>
      </div>
    </div>
  );
}
