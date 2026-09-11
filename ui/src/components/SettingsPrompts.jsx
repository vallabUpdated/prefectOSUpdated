import { useEffect, useMemo, useRef, useState } from "react";
import { applyPromptDefaults } from "../loanJobStore.js";
import { actor as ledgerActor } from "../activityLedger.js";
import "../styles_email.css";

/**
 * SettingsPrompts — the operator's prompt for every document-processing
 * type (home / vehicle / mortgage / personal loans, account statement, KYC,
 * general). What is saved here becomes the default prompt every processing
 * box of that type starts from, and the prompt every job of that type runs
 * with unless the operator edits it on the box itself.
 *
 * Saves via PUT /loan/prompts (Flask). A prompt left equal to the built-in,
 * or emptied, drops the override and the built-in applies again. Open boxes
 * whose prompt has not been hand-edited are updated in place through the
 * job store, so the change is visible without a reload.
 */
const DOMAINS = [
  { id: "loan", label: "Loan processing" },
  { id: "account", label: "Account processing" },
];

export default function SettingsPrompts({ actor = ledgerActor() }) {
  const [types, setTypes] = useState(null);
  const [draft, setDraft] = useState({});        // id -> text
  const [minChars, setMinChars] = useState(20);
  const [open, setOpen] = useState(null);        // id of the expanded editor
  const [state, setState] = useState(null);      // {kind, text}
  const [saving, setSaving] = useState(false);
  const areaRef = useRef(null);

  useEffect(() => {
    fetch("/loan/prompts")
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || `${r.status} ${r.statusText}`);
        return d;
      })
      .then((d) => {
        setTypes(d.types || []);
        setMinChars(d.min_chars || 20);
        setDraft(Object.fromEntries((d.types || []).map((t) => [t.id, t.prompt])));
        setOpen((d.types || [])[0]?.id || null);
      })
      .catch((e) => setState({ kind: "bad", text: `Could not load prompts — ${e.message || e}` }));
  }, []);

  // Size the open editor to its content so the operator never scrolls inside
  // a tiny box while the page itself has room.
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(Math.max(el.scrollHeight, 180), 560) + "px";
  }, [open, draft]);

  const dirty = useMemo(() => {
    if (!types) return [];
    return types.filter((t) => (draft[t.id] ?? "").trim() !== t.prompt.trim()).map((t) => t.id);
  }, [types, draft]);

  if (!types) return <div className="es-section"><div className="es-title">Processing prompts</div>
    <div className="es-note">{state?.text || "Loading…"}</div></div>;

  const tooShort = types.filter((t) => {
    const v = (draft[t.id] ?? "").trim();
    return v && v.length < minChars;
  }).map((t) => t.label);

  const save = async () => {
    setSaving(true); setState(null);
    try {
      const prompts = Object.fromEntries(dirty.map((id) => [id, draft[id]]));
      const r = await fetch("/loan/prompts", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompts, actor }),
      });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || `${r.status} ${r.statusText}`);
      setTypes(d.types);
      setDraft(Object.fromEntries(d.types.map((t) => [t.id, t.prompt])));
      applyPromptDefaults(Object.fromEntries(d.types.map((t) => [t.id, t.prompt])));
      setState({ kind: "ok", text: `Saved — ${dirty.length} prompt${dirty.length === 1 ? "" : "s"} updated; new jobs use them now.` });
    } catch (e) { setState({ kind: "bad", text: String(e.message || e) }); }
    setSaving(false);
  };

  const resetOne = (t) => setDraft({ ...draft, [t.id]: t.builtin_prompt });

  return (
    <div className="es-section">
      <div className="es-note" style={{ marginBottom: 14 }}>
        One prompt per processing type. It is what every box of that type starts
        with and what each job runs against — the eligibility criteria, what to
        extract, and the shape of the answer. An operator can still edit the
        prompt on an individual box before running; that edit applies to that box
        only. Reset returns a type to the built-in prompt shipped with PrefectOS.
      </div>

      {DOMAINS.map((dom) => {
        const rows = types.filter((t) => t.domain === dom.id);
        if (!rows.length) return null;
        return (
          <div key={dom.id} style={{ marginBottom: 18 }}>
            <div className="es-title">{dom.label}</div>
            {rows.map((t) => {
              const isOpen = open === t.id;
              const value = draft[t.id] ?? "";
              const isDirty = dirty.includes(t.id);
              const isBuiltin = value.trim() === t.builtin_prompt.trim();
              return (
                <div className={"es-prompt" + (isOpen ? " open" : "")} key={t.id}>
                  <button type="button" className="es-prompt-head"
                    onClick={() => setOpen(isOpen ? null : t.id)}
                    aria-expanded={isOpen}>
                    <span className="es-prompt-icon" aria-hidden="true">{t.icon}</span>
                    <span className="es-prompt-name">{t.label}</span>
                    <span className="es-prompt-id">{t.id}</span>
                    {isDirty ? <span className="es-pill warn">unsaved</span>
                      : t.customised ? <span className="es-pill on">customised</span>
                      : <span className="es-pill off">built-in</span>}
                    {t.updated_at && !isDirty && (
                      <span className="es-prompt-meta">
                        {new Date(t.updated_at).toLocaleString()}{t.updated_by ? ` · ${t.updated_by}` : ""}
                      </span>
                    )}
                    <span style={{ flex: 1 }} />
                    {!isOpen && <span className="es-prompt-preview">{value.split("\n")[0]}</span>}
                    <span className="es-prompt-chev" aria-hidden="true">{isOpen ? "▾" : "▸"}</span>
                  </button>
                  {isOpen && (
                    <div className="es-prompt-body">
                      <textarea ref={areaRef} value={value} spellCheck={false}
                        onChange={(e) => setDraft({ ...draft, [t.id]: e.target.value })} />
                      <div className="es-prompt-foot">
                        <span className="es-note">
                          {value.trim().length.toLocaleString()} characters
                          {value.trim().length < minChars && value.trim() ? ` — at least ${minChars} needed` : ""}
                        </span>
                        <button type="button" className="es-test" onClick={() => resetOne(t)}
                          disabled={isBuiltin} title="Restore the built-in prompt for this type">
                          Reset to built-in
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}

      <div className="es-row-actions">
        <span className="es-note">
          {dirty.length ? `${dirty.length} unsaved change${dirty.length === 1 ? "" : "s"}.`
            : "Changes apply to new jobs immediately; running jobs keep the prompt they started with."}
        </span>
        {state && <span className={state.kind === "ok" ? "es-ok" : "es-bad"}>{state.text}</span>}
        <button className="es-save" disabled={saving || !dirty.length || tooShort.length > 0}
          title={tooShort.length ? `Too short: ${tooShort.join(", ")}` : ""}
          onClick={save}>
          {saving ? "Saving…" : "Save prompts"}
        </button>
      </div>
    </div>
  );
}
