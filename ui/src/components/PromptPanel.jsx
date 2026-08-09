import { useEffect, useState } from "react";

export default function PromptPanel({ onRun, activeCount = 0, initialPrompt = "", autoFocus = true }) {
  const [activity, setActivity] = useState(initialPrompt);
  const [codebase, setCodebase] = useState("");
  const [starting, setStarting] = useState(false);

  // Pick up a prompt carried over from the home tab's Custom Build section
  useEffect(() => {
    if (initialPrompt) setActivity(initialPrompt);
  }, [initialPrompt]);

  const submit = async () => {
    if (activity.trim().length < 10) {
      alert("Please enter at least 10 characters.");
      return;
    }
    setStarting(true);
    try {
      await onRun(activity.trim(), codebase.trim());
    } finally {
      setStarting(false);
    }
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !starting) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div id="prompt-section">
      <div className="section-label">Activity</div>
      <textarea
        id="prompt"
        rows={3}
        placeholder="e.g. Build a FastAPI task manager with PostgreSQL and GitHub integration"
        value={activity}
        autoFocus={autoFocus}
        onChange={(e) => setActivity(e.target.value)}
        onKeyDown={onKeyDown}
      />
      <div className="section-label" style={{ marginTop: 10 }}>
        Working folder <span className="label-hint">(optional — existing codebase to analyse first)</span>
      </div>
      <input
        id="codebase-input"
        type="text"
        placeholder="e.g. C:\projects\legacy_system"
        value={codebase}
        onChange={(e) => setCodebase(e.target.value)}
        onKeyDown={onKeyDown}
        spellCheck={false}
      />
      <button id="run-btn" disabled={starting} onClick={submit}>
        <div className={"spinner" + (starting ? " show" : "")} />
        <span>{starting ? "Starting…" : activeCount > 0 ? "Run new pipeline" : "Run pipeline"}</span>
      </button>
      {activeCount > 0 && (
        <div className="parallel-hint">
          {activeCount} run{activeCount > 1 ? "s" : ""} active — a new run starts in parallel
        </div>
      )}
    </div>
  );
}
