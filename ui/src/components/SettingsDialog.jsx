import { useEffect, useRef, useState } from "react";
import useOrchestratorTabs, { OPTIONAL_TABS } from "../hooks/useOrchestratorTabs.js";
import SettingsEmail from "./SettingsEmail.jsx";
import SettingsTemplates from "./SettingsTemplates.jsx";
import SettingsPrompts from "./SettingsPrompts.jsx";
import "../styles_settings.css";

// Left-hand navigation. Institution settings are drafted and committed with the
// footer's Save; the email sections carry their own "Save and seal" buttons
// because every change there is sealed to the audit chain individually.
const SECTIONS = [
  { id: "workspace", icon: "🏦", label: "Workspace",
    hint: "Institution, currency, policy pack" },
  { id: "tabs", icon: "🗂", label: "Orchestrator tabs",
    hint: "Optional views in the run window" },
  { id: "prompts", icon: "🧠", label: "Processing prompts",
    hint: "Default prompt per document-processing type", sealed: true },
  { id: "email", icon: "✉️", label: "Email intake",
    hint: "Valid inboxes and sender routes", sealed: true },
  { id: "templates", icon: "📄", label: "Document templates",
    hint: "Keywords and required document sets", sealed: true },
];

/**
 * SettingsDialog — workspace settings, opened from the gear in the header.
 *
 * Holds a draft while open so Cancel genuinely discards; only Save commits,
 * which keeps a half-typed institution name out of a report that starts
 * mid-edit.
 */
export default function SettingsDialog({ open, bankName, fxRate, policyPath, onSave, onClose }) {
  const [draft, setDraft] = useState(bankName || "");
  const [rateDraft, setRateDraft] = useState(String(fxRate ?? ""));
  const [policyDraft, setPolicyDraft] = useState(policyPath || "");
  const [policyState, setPolicyState] = useState(null); // {kind, text}
  const [indexing, setIndexing] = useState(false);
  const inputRef = useRef(null);
  const [section, setSection] = useState("workspace");
  const bodyRef = useRef(null);

  // Optional orchestrator tabs — drafted here, committed with everything else.
  const { tabs, save: saveTabs } = useOrchestratorTabs();
  const [tabDraft, setTabDraft] = useState(tabs);

  useEffect(() => {
    if (!open) return undefined;
    setDraft(bankName || "");
    setRateDraft(String(fxRate ?? ""));
    setPolicyDraft(policyPath || "");
    setPolicyState(null);
    setTabDraft(tabs);
    setSection("workspace");
    // Focus after paint so the field is ready to type into.
    const id = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(id);
  }, [open, bankName, fxRate, policyPath]);

  // Report what the pack looks like on disk as the operator types, so a wrong
  // path is obvious before a run depends on it.
  useEffect(() => {
    if (!open) return undefined;
    const path = policyDraft.trim();
    if (!path) {
      setPolicyState(null);
      return undefined;
    }
    let cancelled = false;
    const id = setTimeout(() => {
      fetch(`/loan/policy/status?path=${encodeURIComponent(path)}`)
        .then((r) => r.json())
        .then((d) => {
          if (cancelled) return;
          if (!d.exists) setPolicyState({ kind: "bad", text: d.detail || "Folder not found." });
          else if (!d.indexed) setPolicyState({ kind: "warn", text: "Found, not indexed yet." });
          else if (d.stale) setPolicyState({ kind: "warn", text: `${d.chunks} clauses indexed — the folder changed since.` });
          else setPolicyState({ kind: "ok", text: `${d.chunks} clauses from ${d.files_indexed} documents.` });
        })
        .catch(() => !cancelled && setPolicyState({ kind: "bad", text: "Could not reach the server." }));
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(id);
    };
  }, [open, policyDraft]);

  const indexPack = () => {
    const path = policyDraft.trim();
    if (!path) return;
    setIndexing(true);
    fetch("/loan/policy/index", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, force: true }),
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Indexing failed.");
        setPolicyState({
          kind: "ok",
          text: `${d.chunks} clauses from ${d.files_indexed} documents, ${Math.round(d.index_ms)} ms.`,
        });
      })
      .catch((e) => setPolicyState({ kind: "bad", text: e.message }))
      .finally(() => setIndexing(false));
  };

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: 0 });
  }, [section]);

  if (!open) return null;

  const active = SECTIONS.find((x) => x.id === section) || SECTIONS[0];
  const parsedRate = Number.parseFloat(rateDraft);
  const rateValid = Number.isFinite(parsedRate) && parsedRate > 0;

  const commit = () => {
    if (!rateValid) return;
    onSave({ bankName: draft.trim(), fxRate: parsedRate, policyPath: policyDraft.trim() });
    saveTabs(tabDraft);
    onClose();
  };

  return (
    <div
      className="st-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="st-title"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="st st-wide">
        <header className="st-head">
          <div className="st-title" id="st-title">Settings</div>
          <button className="st-close" onClick={onClose} aria-label="Close settings">✕</button>
        </header>

        <div className="st-layout">
          <nav className="st-nav" aria-label="Settings sections">
            {SECTIONS.map((x) => (
              <button
                key={x.id}
                type="button"
                className={"st-nav-item" + (x.id === section ? " active" : "")}
                aria-current={x.id === section ? "page" : undefined}
                onClick={() => setSection(x.id)}
              >
                <span className="st-nav-icon" aria-hidden="true">{x.icon}</span>
                <span className="st-nav-text">
                  <span className="st-nav-label">{x.label}</span>
                  <span className="st-nav-hint">{x.hint}</span>
                </span>
              </button>
            ))}
          </nav>

          <div className="st-body st-pane" ref={bodyRef}>
          <div className="st-pane-head">
            <div className="st-pane-title">{active.label}</div>
            <div className="st-pane-sub">{active.hint}</div>
          </div>

          {section === "workspace" && (<>
          <label className="st-field" htmlFor="st-bank">
            <span className="st-label">Bank / institution</span>
            <input
              id="st-bank"
              ref={inputRef}
              className="st-input"
              value={draft}
              placeholder="e.g. Demo Finance Bank"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && commit()}
            />
            <span className="st-hint">
              Shown beside the product name here, and in the header and footer of
              every report this workspace generates.
            </span>
          </label>

          <label className="st-field" htmlFor="st-fx">
            <span className="st-label">Exchange rate — ₹ per US$1</span>
            <input
              id="st-fx"
              className={"st-input" + (rateValid ? "" : " invalid")}
              type="number"
              min="0.01"
              step="0.01"
              value={rateDraft}
              onChange={(e) => setRateDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && commit()}
            />
            <span className="st-hint">
              Costs are billed by Anthropic in US dollars. This rate converts them
              to rupees for display — set it to the rate your finance team uses;
              it is not fetched live.
              {!rateValid && (
                <strong className="st-invalid"> Enter a rate above zero.</strong>
              )}
            </span>
          </label>

          <label className="st-field" htmlFor="st-policy">
            <span className="st-label">
              Credit policy pack <span className="st-optional">optional</span>
            </span>
            <div className="st-row">
              <input
                id="st-policy"
                className="st-input"
                value={policyDraft}
                placeholder="Folder holding the bank's credit policy documents"
                onChange={(e) => setPolicyDraft(e.target.value)}
              />
              <button
                type="button"
                className="st-btn"
                onClick={indexPack}
                disabled={!policyDraft.trim() || indexing}
                title="Read the documents and build the retrieval index"
              >
                {indexing ? "Indexing…" : "Index"}
              </button>
            </div>
            {policyState && (
              <span className={"st-packstate " + policyState.kind}>{policyState.text}</span>
            )}
            <span className="st-hint">
              Point this at the folder holding your credit policy (PDF, DOCX, or
              text). Boxes with <strong>Cite policy</strong> switched on retrieve
              the clauses that bear on the run and pass them to the Processing
              Agent, which then cites them by clause number. Indexing is one-off;
              retrieval adds no API call.
            </span>
          </label>

          </>)}

          {section === "tabs" && (
          <div className="st-field">
            <span className="st-label">Orchestrator tabs</span>
            <div className="st-toggles">
              {OPTIONAL_TABS.map((t) => (
                <label className="st-toggle" key={t.id}>
                  <input
                    type="checkbox"
                    checked={!!tabDraft[t.id]}
                    onChange={(e) => setTabDraft({ ...tabDraft, [t.id]: e.target.checked })}
                  />
                  <span className="st-toggle-body">
                    <span className="st-toggle-label">{t.label}</span>
                    <span className="st-toggle-hint">{t.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <span className="st-hint">
              Off by default: the orchestrator opens straight on Live run. Switch
              a tab on to have it appear in the orchestrator's tab bar.
            </span>
          </div>
          )}

          {/* Email intake configuration: valid inboxes + document templates.
              Self-contained panes with their own sealed saves — independent of
              the dialog's draft/commit cycle for institution settings. */}
          {section === "prompts" && <SettingsPrompts />}
          {section === "email" && <SettingsEmail />}
          {section === "templates" && <SettingsTemplates />}
          </div>
        </div>

        <footer className="st-foot">
          {active.sealed ? (<>
            <span className="st-foot-note">
              {section === "prompts"
                ? <>Changes here are saved with <strong>Save prompts</strong> above and
                    recorded in the activity ledger.</>
                : <>Changes here are saved with <strong>Save and seal</strong> above and
                    recorded in the audit chain.</>}
            </span>
            <button className="st-btn" onClick={onClose}>Close</button>
          </>) : (<>
            <span className="st-foot-note">Applies to the workspace and every report it generates.</span>
            <button className="st-btn" onClick={onClose}>Cancel</button>
            <button className="st-btn st-btn-primary" onClick={commit} disabled={!rateValid}>
              Save
            </button>
          </>)}
        </footer>
      </div>
    </div>
  );
}
