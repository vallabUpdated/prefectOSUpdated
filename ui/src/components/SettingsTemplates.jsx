import { useEffect, useState } from "react";
import "../styles_email.css";

/**
 * SettingsTemplates — document template + required-set configuration
 * for Loans / KYC / Accounts. Edits keywords, any-N markers and page
 * bounds per template, and the required document set per product.
 * Saves via PUT /email/templates; sealed as template_updated.
 */
const GROUPS = {
  Loans: ["application_form", "identity_proof", "income_proof", "property_document"],
  KYC: ["kyc_form"],
  Accounts: ["bank_statement"],
};

export default function SettingsTemplates({ approver = "system-admin" }) {
  const [data, setData] = useState(null);
  const [group, setGroup] = useState("Loans");
  const [state, setState] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    fetch("/email/templates").then((r) => r.json()).then(setData)
      .catch(() => setState({ kind: "bad", text: "Email intake API unreachable." }));
  }, []);

  if (!data) return <div className="es-section"><div className="es-title">Document templates</div>
    <div className="es-note">{state?.text || "Loading…"}</div></div>;

  const inGroup = (t) => {
    const g = Object.entries(GROUPS).find(([, types]) => types.includes(t.doc_type));
    return (g ? g[0] : "Loans") === group;
  };

  const setTpl = (docType, patch) =>
    setData({
      ...data,
      templates: data.templates.map((t) =>
        t.doc_type === docType ? { ...t, ...patch } : t),
    });

  const addKw = (t, field) => {
    const kw = window.prompt(`Add keyword to "${t.label}" (${field === "required_keywords" ? "must contain" : "any-of markers"}):`);
    if (kw?.trim()) setTpl(t.doc_type, { [field]: [...(t[field] || []), kw.trim().toLowerCase()] });
  };

  const dropKw = (t, field, kw) =>
    setTpl(t.doc_type, { [field]: t[field].filter((k) => k !== kw) });

  const dropFromSet = (product, dt) =>
    setData({
      ...data,
      document_sets: {
        ...data.document_sets,
        [product]: data.document_sets[product].filter((d) => d !== dt),
      },
    });

  const addToSet = (product) => {
    const options = data.templates.map((t) => t.doc_type)
      .filter((d) => !data.document_sets[product].includes(d));
    if (!options.length) return;
    const dt = window.prompt(`Add doc type to ${product} set:\n${options.join(", ")}`);
    if (dt && options.includes(dt.trim()))
      setData({
        ...data,
        document_sets: {
          ...data.document_sets,
          [product]: [...data.document_sets[product], dt.trim()],
        },
      });
  };

  const save = async () => {
    setSaving(true); setState(null);
    try {
      const r = await fetch(`/email/templates?approver=${encodeURIComponent(approver)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      setState({ kind: "ok", text: "Saved and sealed — applies next poll." });
    } catch (e) { setState({ kind: "bad", text: String(e.message || e) }); }
    setSaving(false);
  };

  return (
    <div className="es-section">
      <div className="es-title">
        Document templates
        <span style={{ marginLeft: 10, display: "inline-flex", gap: 4 }}>
          {Object.keys(GROUPS).map((g) => (
            <button key={g} className="es-add" style={{
              padding: "2px 10px",
              background: group === g ? "#eef2ff" : "transparent",
              borderRadius: 7, textTransform: "none", letterSpacing: 0,
            }} onClick={() => setGroup(g)}>{g}</button>
          ))}
        </span>
      </div>

      {data.templates.filter(inGroup).map((t) => (
        <div className="es-tpl" key={t.doc_type}>
          <div className="es-tpl-head">
            <span className="es-tpl-name">{t.label}</span>
            <span className="es-tpl-meta">{t.doc_type} · {t.min_pages ?? 1}–{t.max_pages ?? 200} pages</span>
          </div>
          <div className="es-kw">
            <span>must contain:</span>
            {(t.required_keywords || []).map((k) => (
              <span className="es-kw-req" key={k}>{k}
                <button onClick={() => dropKw(t, "required_keywords", k)}>✕</button></span>
            ))}
            <button className="es-add" style={{ padding: 0 }}
              onClick={() => addKw(t, "required_keywords")}>+ add</button>
            <span style={{ marginLeft: 8 }}>any {t.min_any ?? 1} of:</span>
            {(t.any_keywords || []).map((k) => (
              <span className="es-kw-any" key={k}>{k}
                <button onClick={() => dropKw(t, "any_keywords", k)}>✕</button></span>
            ))}
            <button className="es-add" style={{ padding: 0 }}
              onClick={() => addKw(t, "any_keywords")}>+ add</button>
          </div>
        </div>
      ))}

      <div className="es-title" style={{ marginTop: 14 }}>Required document sets</div>
      {Object.entries(data.document_sets).map(([product, req]) => (
        <div key={product}>
          <div className="es-tpl-meta" style={{ margin: "4px 0" }}>{product}</div>
          <div className="es-set">
            {req.map((dt) => (
              <span className="es-set-chip" key={dt}>✔ {dt}
                <button onClick={() => dropFromSet(product, dt)}>✕</button></span>
            ))}
            <button className="es-add" style={{ padding: "3px 10px" }}
              onClick={() => addToSet(product)}>+ add doc type</button>
          </div>
        </div>
      ))}

      <div className="es-row-actions">
        <span className="es-note">
          Template changes silently change what is accepted from every
          client — saves are versioned into the audit chain.
        </span>
        {state && <span className={state.kind === "ok" ? "es-ok" : "es-bad"}>{state.text}</span>}
        <button className="es-save" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save and seal"}
        </button>
      </div>
    </div>
  );
}
