import { useCallback, useEffect, useState } from "react";
import "../styles_email.css";

/**
 * SettingsEmail — intake mailboxes + sender routes.
 *
 * Mailboxes: the built-in "default" box (the config's top-level imap_*
 * fields) plus any dedicated per-client boxes in `mailboxes[]`, each living
 * in the client's own tenant. Routes bind to a mailbox by id; the sender
 * allowlist is scoped to that mailbox, so a sender allowed into client A's
 * box is not thereby allowed into client B's. "*" allows any sender —
 * meant for a dedicated box that only ever receives applicant mail.
 *
 * Secrets never pass through here: each mailbox names the environment
 * variable (secret_env) that holds its password / client secret / key
 * path on the connector host. Saves go via PUT /email/settings and are
 * sealed to the email audit chain as routes_updated.
 */

const DEFAULT_ID = "default";
const AUTHS = [
  { id: "password", label: "Password / app password" },
  { id: "oauth_microsoft", label: "Microsoft 365 — OAuth (client credentials)" },
  { id: "oauth_google", label: "Google Workspace — OAuth (service account)" },
];
const PROVIDERS = [
  { id: "generic", label: "Generic IMAP", host: "" },
  { id: "google", label: "Google Workspace", host: "imap.gmail.com" },
  { id: "microsoft", label: "Microsoft 365", host: "outlook.office365.com" },
];
const SECRET_HINT = {
  password: "Env var holding the mailbox password or app password.",
  oauth_microsoft: "Env var holding the Entra app's client secret.",
  oauth_google: "Env var holding the PATH to the service-account JSON key.",
};

// The default mailbox is stored flat on the config; present it like the others.
const DEFAULT_KEYS = {
  imap_host: "imap_host", imap_user: "imap_user", imap_port: "imap_port",
  folder: "mailbox", provider: "provider", auth: "auth", secret_env: "secret_env",
  tenant_id: "tenant_id", oauth_client_id: "oauth_client_id",
};
const defaultBox = (cfg) => ({
  id: DEFAULT_ID, label: "Default intake mailbox",
  imap_host: cfg.imap_host || "", imap_user: cfg.imap_user || "",
  imap_port: cfg.imap_port ?? 993, folder: cfg.mailbox || "INBOX",
  provider: cfg.provider || "generic", auth: cfg.auth || "password",
  secret_env: cfg.secret_env || "EMAIL_INGEST_PASSWORD",
  tenant_id: cfg.tenant_id || "", oauth_client_id: cfg.oauth_client_id || "",
});
const slug = (s) => s.toLowerCase().replace(/[^a-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "");

async function jsonOrThrow(r) {
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || `${r.status} ${r.statusText}`);
  return d;
}

export default function SettingsEmail({ approver = "system-admin", products = [] }) {
  const [cfg, setCfg] = useState(null);
  const [health, setHealth] = useState({});      // mailbox id -> live status row
  const [state, setState] = useState(null);      // {kind:"ok"|"bad", text}
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState({});    // mailbox id -> result | "…"

  const loadHealth = useCallback(() => {
    fetch("/email/mailboxes").then(jsonOrThrow)
      .then((d) => setHealth(Object.fromEntries(d.mailboxes.map((m) => [m.id, m]))))
      .catch(() => {});                          // health is advisory only
  }, []);

  useEffect(() => {
    fetch("/email/settings").then(jsonOrThrow).then(setCfg)
      .catch((e) => setState({ kind: "bad", text: `Email intake API unreachable — ${e.message || e}` }));
    loadHealth();
  }, [loadHealth]);

  if (!cfg) return <div className="es-section"><div className="es-title">Email intake</div>
    <div className="es-note">{state?.text || "Loading…"}</div></div>;

  const productOpts = products.length ? products
    : ["home_loan", "vehicle_loan", "personal_loan", "kyc", "statement"];
  const boxes = [defaultBox(cfg), ...(cfg.mailboxes || [])];
  const boundTo = (id) => cfg.routes.filter((r) => (r.mailbox || DEFAULT_ID) === id).length;

  // ── mailbox edits ──────────────────────────────────────────────────
  const setBox = (id, patch) => {
    if (id === DEFAULT_ID) {
      const flat = {};
      for (const [k, v] of Object.entries(patch)) flat[DEFAULT_KEYS[k] || k] = v;
      setCfg({ ...cfg, ...flat });
    } else {
      setCfg({ ...cfg, mailboxes: cfg.mailboxes.map((m) => (m.id === id ? { ...m, ...patch } : m)) });
    }
  };
  const setProvider = (id, provider) => {
    const p = PROVIDERS.find((x) => x.id === provider);
    const patch = { provider };
    if (p?.host) patch.imap_host = p.host;
    if (provider === "microsoft") patch.auth = "oauth_microsoft";
    if (provider === "google") patch.auth = "oauth_google";
    setBox(id, patch);
  };
  const addBox = () => {
    const n = (cfg.mailboxes || []).length + 1;
    setCfg({
      ...cfg,
      mailboxes: [...(cfg.mailboxes || []), {
        id: `client_${n}`, label: `Client ${n} intake`, provider: "generic",
        imap_host: "", imap_port: 993, imap_user: "", folder: "INBOX",
        auth: "password", secret_env: `CLIENT_${n}_INTAKE_SECRET`,
        tenant_id: "", oauth_client_id: "",
      }],
    });
  };
  const removeBox = (id) => {
    if (boundTo(id)) return;
    setCfg({ ...cfg, mailboxes: cfg.mailboxes.filter((m) => m.id !== id) });
  };
  const renameBox = (id, next) => {
    const nid = slug(next) || id;
    if (nid === DEFAULT_ID || boxes.some((m) => m.id === nid && m.id !== id)) return;
    setCfg({
      ...cfg,
      mailboxes: cfg.mailboxes.map((m) => (m.id === id ? { ...m, id: nid } : m)),
      routes: cfg.routes.map((r) => (r.mailbox === id ? { ...r, mailbox: nid } : r)),
    });
  };

  const testBox = async (box) => {
    setTesting({ ...testing, [box.id]: "…" });
    try {
      const r = await fetch("/email/mailboxes/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mailbox: box }),
      });
      const result = await jsonOrThrow(r);
      setTesting((t) => ({ ...t, [box.id]: result }));
    } catch (e) {
      setTesting((t) => ({ ...t, [box.id]: { ok: false, error: e.message || String(e) } }));
    }
  };

  // ── route edits ────────────────────────────────────────────────────
  const setRoute = (i, patch) =>
    setCfg({ ...cfg, routes: cfg.routes.map((r, j) => (j === i ? { ...r, ...patch } : r)) });

  const save = async () => {
    setSaving(true); setState(null);
    try {
      const r = await fetch(`/email/settings?approver=${encodeURIComponent(approver)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cfg),
      });
      await jsonOrThrow(r);
      setState({ kind: "ok", text: "Saved and sealed — applies next poll." });
      loadHealth();
    } catch (e) { setState({ kind: "bad", text: String(e.message || e) }); }
    setSaving(false);
  };

  return (
    <div className="es-section">
      <div className="es-title">Intake mailboxes</div>
      <div className="es-note" style={{ marginBottom: 12 }}>
        Each mailbox is polled by the connector. Dedicated mailboxes live in the
        client's own tenant; PrefectOS reads only the folder named here and files
        handled mail under <span className="es-mono">PrefectOS/Processed</span> /
        <span className="es-mono">PrefectOS/Rejected</span>. Secrets stay on the
        connector host — only the environment variable's <em>name</em> is stored.
      </div>

      {boxes.map((box) => {
        const h = health[box.id] || {};
        const st = h.status || {};
        const t = testing[box.id];
        const bound = boundTo(box.id);
        const isDefault = box.id === DEFAULT_ID;
        return (
          <div className="es-mbx" key={box.id}>
            <div className="es-mbx-head">
              <input className="es-mbx-label" value={box.label || ""}
                placeholder={isDefault ? "Default intake mailbox" : "Mailbox label"}
                onChange={(e) => setBox(box.id, { label: e.target.value })} />
              <span className="es-mbx-id" title="Mailbox id — routes bind to this">
                {isDefault ? "default" : (
                  <input value={box.id} onChange={(e) => renameBox(box.id, e.target.value)}
                    title="Mailbox id (letters, digits, _ -)" />
                )}
              </span>
              <span className={"es-pill " + (h.polled ? "on" : "off")}>
                {h.polled ? "polled" : "not polled"}
              </span>
              <span className="es-pill">{bound} route{bound === 1 ? "" : "s"}</span>
              <span className={"es-pill " + (h.secret_present ? "on" : "warn")}
                title={`Is ${box.secret_env} set in the API server's environment?`}>
                {h.secret_present ? "secret present" : "secret missing"}
              </span>
              <span style={{ flex: 1 }} />
              <button className="es-test" onClick={() => testBox(box)} disabled={t === "…"}>
                {t === "…" ? "Testing…" : "Test connection"}
              </button>
              {!isDefault && (
                <button className="es-del" onClick={() => removeBox(box.id)} disabled={!!bound}
                  title={bound ? "Unbind its routes first" : "Remove mailbox"}>✕</button>
              )}
            </div>

            <div className="es-grid">
              <label>Provider
                <select value={box.provider || "generic"}
                  onChange={(e) => setProvider(box.id, e.target.value)}>
                  {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
              </label>
              <label>IMAP host
                <input value={box.imap_host} placeholder="imap.example.com"
                  onChange={(e) => setBox(box.id, { imap_host: e.target.value })} />
              </label>
              <label>Port
                <input type="number" value={box.imap_port ?? 993} min="1" max="65535"
                  onChange={(e) => setBox(box.id, { imap_port: Number(e.target.value) || 993 })} />
              </label>
              <label>Mailbox address
                <input value={box.imap_user} placeholder="prefectos-intake@client.com"
                  onChange={(e) => setBox(box.id, { imap_user: e.target.value })} />
              </label>
              <label>Folder
                <input value={box.folder || "INBOX"}
                  onChange={(e) => setBox(box.id, { folder: e.target.value })} />
              </label>
              <label>Authentication
                <select value={box.auth || "password"}
                  onChange={(e) => setBox(box.id, { auth: e.target.value })}>
                  {AUTHS.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              </label>
              <label title={SECRET_HINT[box.auth] || ""}>Secret env var
                <input className="es-mono-in" value={box.secret_env || ""}
                  placeholder="CLIENT_INTAKE_SECRET"
                  onChange={(e) => setBox(box.id, { secret_env: e.target.value.toUpperCase() })} />
              </label>
              {box.auth === "oauth_microsoft" && (<>
                <label>Tenant ID
                  <input className="es-mono-in" value={box.tenant_id || ""}
                    onChange={(e) => setBox(box.id, { tenant_id: e.target.value })} />
                </label>
                <label>App (client) ID
                  <input className="es-mono-in" value={box.oauth_client_id || ""}
                    onChange={(e) => setBox(box.id, { oauth_client_id: e.target.value })} />
                </label>
              </>)}
            </div>

            <div className="es-mbx-foot">
              <span className="es-note">{SECRET_HINT[box.auth]}</span>
              {st.last_poll && (
                <span className={"es-status-line " + (st.last_error ? "bad" : "ok")}
                  title={st.last_error || ""}>
                  {st.last_error
                    ? `Last poll failed: ${st.last_error}`
                    : `Last poll ${new Date(st.last_poll).toLocaleString()} — ` +
                      `${st.scanned ?? 0} scanned, ${st.accepted ?? 0} accepted, ${st.rejected ?? 0} rejected`}
                </span>
              )}
              {t && t !== "…" && (
                <span className={"es-status-line " + (t.ok ? "ok" : "bad")}>
                  {t.ok ? `Connected — ${t.unseen} unread in ${t.folder} (${t.ms} ms)` : t.error}
                </span>
              )}
            </div>
          </div>
        );
      })}
      <button className="es-add" onClick={addBox}>+ Add dedicated client mailbox</button>

      <div className="es-title" style={{ marginTop: 22 }}>Sender routes</div>
      <div className="es-box">
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={!!cfg.require_authentication}
            onChange={(e) => setCfg({ ...cfg, require_authentication: e.target.checked })} />
          Require SPF/DKIM pass (anti-spoofing) — applies to every mailbox
        </label>
      </div>

      <div className="es-note" style={{ marginBottom: 10 }}>
        A route says <strong>who may email a mailbox</strong> and which client workspace and
        product their documents belong to. <em>Allowed senders</em> is the applicant's or
        client's <em>From</em> address — never the intake mailbox's own address. Use{" "}
        <span className="es-mono">*</span> to accept anyone into a dedicated mailbox, or{" "}
        <span className="es-mono">*@client.com</span> for a whole domain. Product{" "}
        <span className="es-mono">auto</span> lets one mailbox take several products: the
        product is read from the subject line (e.g. "Vehicle Loan Docs") or, failing that,
        from which document set the attachments complete.
      </div>
      <div className="es-table">
        <div className="es-th">
          <span>Allowed senders (From)</span>
          <span>Mailbox</span>
          <span>Client workspace</span>
          <span>Product</span>
          <span />
        </div>
        {cfg.routes.map((r, i) => {
          const ownAddrs = boxes.map((m) => (m.imap_user || "").toLowerCase()).filter(Boolean);
          const selfSender = r.senders.find((x) => ownAddrs.includes(x.toLowerCase()));
          return (
          <div className={"es-tr" + (selfSender ? " es-tr-warn" : "")} key={i}
            title={selfSender ? `${selfSender} is an intake mailbox, not a sender — enter who emails it (or *)` : ""}>
            <input value={r.senders.join(", ")}
              style={selfSender ? { borderColor: "#f59e0b", background: "#fffbeb" } : undefined}
              title='Allowed senders — exact addresses, *@domain, or * for any sender (dedicated mailboxes), comma-separated'
              placeholder="ops@client.com, *@client.com, or *"
              onChange={(e) => setRoute(i, {
                senders: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
              })} />
            <select value={r.mailbox || DEFAULT_ID} style={{ flex: "0 0 120px" }}
              title="Which mailbox this route reads from"
              onChange={(e) => setRoute(i, { mailbox: e.target.value })}>
              {boxes.map((m) => (
                <option key={m.id} value={m.id}>{m.id === DEFAULT_ID ? "default" : m.id}</option>
              ))}
            </select>
            <input value={r.client_id} style={{ flex: "0 0 130px" }}
              title="Client workspace id"
              onChange={(e) => setRoute(i, { client_id: e.target.value })} />
            <select value={r.product || ""}
              onChange={(e) => setRoute(i, { product: e.target.value || null })}>
              <option value="">(no product)</option>
              <option value="auto">auto — from subject / documents</option>
              {productOpts.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <button className="es-del" title="Remove route"
              onClick={() => setCfg({ ...cfg, routes: cfg.routes.filter((_, j) => j !== i) })}>
              ✕
            </button>
          </div>
          );
        })}
        <button className="es-add"
          onClick={() => setCfg({
            ...cfg,
            routes: [...cfg.routes, { client_id: "", product: null, senders: [], mailbox: DEFAULT_ID }],
          })}>
          + Add sender route
        </button>
      </div>

      <div className="es-row-actions">
        <span className="es-note">
          Mail from any address not listed for its mailbox is rejected and ledgered.
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
