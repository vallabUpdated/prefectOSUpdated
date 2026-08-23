import { useEffect, useRef, useState } from "react";
import useOrchestratorTabs, { OPTIONAL_TABS } from "../hooks/useOrchestratorTabs.js";
import "../styles_settings.css";

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

  if (!open) return null;

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
      <div className="st">
        <header className="st-head">
          <div className="st-title" id="st-title">Settings</div>
          <button className="st-close" onClick={onClose} aria-label="Close settings">✕</button>
        </header>

        <div className="st-body">
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
        </div>

        <footer className="st-foot">
          <button className="st-btn" onClick={onClose}>Cancel</button>
          <button className="st-btn st-btn-primary" onClick={commit} disabled={!rateValid}>
            Save
          </button>
        </footer>
      </div>
    </div>
  );
}
