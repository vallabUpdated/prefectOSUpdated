import { useEffect, useMemo, useState } from "react";

/**
 * StartRun — the daily "new pipeline" screen for SME teams.
 *
 * Adds over PromptPanel: activity templates, explicit run type, three
 * codebase sources (path / git / previously-indexed), a required client
 * tag, per-run provider choice, and a collapsed governance section
 * (RAG toggle + backend, skill preview, venv, read-only agent budget).
 *
 * Backend payload (POST /run):
 *   { activity, run_type, client_tag, provider,
 *     codebase: { source: "path"|"git"|"indexed", path?, git_url?, git_branch?, collection? },
 *     rag: { enabled, backend }, skills_excluded: [], no_venv }
 */

const TEMPLATES = [
  { id: "blank",      label: "Blank",             body: "" },
  { id: "bugfix",     label: "Bug fix",
    body: "Fix the following defect:\n\nObserved behaviour:\n\nExpected behaviour:\n\nAffected module/screen:\n\nConstraints (do not change):" },
  { id: "enhance",    label: "Enhancement",
    body: "Enhance the existing system as follows:\n\nCurrent behaviour:\n\nDesired behaviour:\n\nBusiness reason:\n\nOut of scope:" },
  { id: "compliance", label: "Compliance change",
    body: "Implement the following compliance requirement:\n\nRegulation / clause:\n\nObligation:\n\nSystems affected:\n\nEvidence required by client:" },
  { id: "module",     label: "New module",
    body: "Build a new module:\n\nPurpose:\n\nKey entities:\n\nIntegrations:\n\nNon-functional requirements:" },
];

export default function StartRun({
  onRun,                       // (payload) => Promise
  clients = [],                // [{id, name, policy: {providers: ["anthropic","ollama"]}}]
  indexedCodebases = [],       // [{collection, label, chunks}]
  matchedSkills = [],          // [{skill_id, name}] — live preview from GET /skills/match?activity=
  onActivityChange,            // (text) => void, lets parent fetch skill matches
  activeCount = 0,
  maxAgents = 10,
  initialActivity = "",        // handed off from the Home landing page
  initialCodebase = null,      // {source: "path"|"git", path?, git_url?, git_branch?} | null
  handoffNonce = 0,            // bumps once per Home → orchestrator handoff
}) {
  const [activity, setActivity]   = useState("");
  const [template, setTemplate]   = useState("blank");
  const [runType, setRunType]     = useState("greenfield"); // greenfield | govern
  const [clientTag, setClientTag] = useState("");
  const [provider, setProvider]   = useState("anthropic");

  const [srcKind, setSrcKind]     = useState("path");       // path | git | indexed
  const [path, setPath]           = useState("");
  const [gitUrl, setGitUrl]       = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [collection, setCollection] = useState("");

  const [advOpen, setAdvOpen]     = useState(false);
  const [ragOn, setRagOn]         = useState(true);
  const [ragBackend, setRagBackend] = useState("auto");
  const [excludedSkills, setExcludedSkills] = useState([]);
  const [noVenv, setNoVenv]       = useState(false);

  const [starting, setStarting]   = useState(false);
  const [error, setError]         = useState("");

  // Hydrate from the Home landing page handoff — fires exactly once per
  // handoff (nonce bump), so it never clobbers text typed or template-applied
  // here. The user still reviews and presses "Start governed run" below;
  // Home never auto-starts a pipeline.
  useEffect(() => {
    if (!handoffNonce) return;
    if (initialActivity) {
      setActivity(initialActivity);
      onActivityChange?.(initialActivity);
    }
    if (initialCodebase) {
      setRunType("govern");
      if (initialCodebase.source === "git") {
        setSrcKind("git");
        setGitUrl(initialCodebase.git_url || "");
        setGitBranch(initialCodebase.git_branch || "main");
      } else {
        setSrcKind("path");
        setPath(initialCodebase.path || "");
      }
    }
  }, [handoffNonce]); // eslint-disable-line react-hooks/exhaustive-deps

  const client = useMemo(
    () => clients.find((c) => c.id === clientTag) || null,
    [clients, clientTag]
  );
  const allowedProviders = client?.policy?.providers || ["anthropic", "ollama"];

  // Enforce client provider policy (e.g. "Client X = local models only")
  useEffect(() => {
    if (!allowedProviders.includes(provider)) setProvider(allowedProviders[0]);
  }, [clientTag]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyTemplate = (id) => {
    setTemplate(id);
    const t = TEMPLATES.find((t) => t.id === id);
    if (t && t.body && !activity.trim()) setActivity(t.body);
    else if (t && t.body && window.confirm("Replace current activity text with the template?"))
      setActivity(t.body);
  };

  const updateActivity = (v) => {
    setActivity(v);
    onActivityChange?.(v);
  };

  const toggleSkill = (id) =>
    setExcludedSkills((xs) =>
      xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]
    );

  const validate = () => {
    if (activity.trim().length < 10) return "Describe the activity (at least 10 characters).";
    if (!clientTag) return "Select a client / engagement — every artifact is segregated by it.";
    if (runType === "govern") {
      if (srcKind === "path" && !path.trim())      return "Provide the codebase path.";
      if (srcKind === "git" && !gitUrl.trim())     return "Provide the git repository URL.";
      if (srcKind === "indexed" && !collection)    return "Pick a previously indexed codebase.";
    }
    return "";
  };

  const submit = async () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError("");
    setStarting(true);
    try {
      await onRun({
        activity: activity.trim(),
        run_type: runType,
        client_tag: clientTag,
        provider,
        codebase:
          runType === "govern"
            ? srcKind === "path"
              ? { source: "path", path: path.trim() }
              : srcKind === "git"
              ? { source: "git", git_url: gitUrl.trim(), git_branch: gitBranch.trim() || "main" }
              : { source: "indexed", collection }
            : null,
        rag: { enabled: runType === "govern" ? ragOn : false, backend: ragBackend },
        skills_excluded: excludedSkills,
        no_venv: noVenv,
      });
    } finally {
      setStarting(false);
    }
  };

  return (
    <div id="start-run">
      {/* ── Activity ─────────────────────────────────────────────── */}
      <div className="section-label">Activity</div>
      <div className="sr-templates" style={{ marginBottom: "8px" }}>
        {TEMPLATES.map((t) => (
          <button
            key={t.id}
            className={"sr-chip" + (template === t.id ? " on" : "")}
            onClick={() => applyTemplate(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <textarea
        id="prompt"
        rows={6}
        placeholder="Describe the work in plain language — what, why, and any constraints"
        value={activity}
        autoFocus
        onChange={(e) => updateActivity(e.target.value)}
      />

      {/* ── Run type + client + provider ─────────────────────────── */}
      <div className="sr-grid3">
        <div>
          <div className="section-label">Run type</div>
          <div className="sr-seg">
            <button
              className={runType === "greenfield" ? "on" : ""}
              onClick={() => setRunType("greenfield")}
            >
              Greenfield
            </button>
            <button
              className={runType === "govern" ? "on" : ""}
              onClick={() => setRunType("govern")}
              title="Comprehend + index an existing codebase, then plan against it"
            >
              Govern / Enhance existing
            </button>
          </div>
        </div>

        <div>
          <div className="section-label">
            Client / engagement <span className="sr-req">required</span>
          </div>
          <select value={clientTag} onChange={(e) => setClientTag(e.target.value)}>
            <option value="">— select —</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>

        <div>
          <div className="section-label">Model provider</div>
          <select value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="anthropic" disabled={!allowedProviders.includes("anthropic")}>
              Anthropic (Claude API)
            </option>
            <option value="ollama" disabled={!allowedProviders.includes("ollama")}>
              Ollama (local — data never leaves this machine)
            </option>
          </select>
          {client && allowedProviders.length === 1 && (
            <div className="sr-policy-note">
              {client.name} policy: {allowedProviders[0]} only
            </div>
          )}
        </div>
      </div>

      {/* ── Codebase source (govern/enhance only) ────────────────── */}
      {runType === "govern" && (
        <div className="sr-codebase">
          <div className="section-label">Existing codebase</div>
          <div className="sr-seg sr-seg-sm">
            <button className={srcKind === "path" ? "on" : ""} onClick={() => setSrcKind("path")}>
              Server path
            </button>
            <button className={srcKind === "git" ? "on" : ""} onClick={() => setSrcKind("git")}>
              Git repository
            </button>
            <button
              className={srcKind === "indexed" ? "on" : ""}
              onClick={() => setSrcKind("indexed")}
              disabled={indexedCodebases.length === 0}
              title={indexedCodebases.length === 0 ? "No codebases indexed yet" : ""}
            >
              Previously indexed ({indexedCodebases.length})
            </button>
          </div>

          {srcKind === "path" && (
            <input
              type="text"
              placeholder={"e.g. C:\\clients\\acmebank\\core_ledger"}
              value={path}
              onChange={(e) => setPath(e.target.value)}
              spellCheck={false}
            />
          )}
          {srcKind === "git" && (
            <div className="sr-git">
              <input
                type="text"
                placeholder="https://github.com/org/repo.git"
                value={gitUrl}
                onChange={(e) => setGitUrl(e.target.value)}
                spellCheck={false}
              />
              <input
                type="text"
                className="sr-branch"
                placeholder="branch"
                value={gitBranch}
                onChange={(e) => setGitBranch(e.target.value)}
                spellCheck={false}
              />
            </div>
          )}
          {srcKind === "indexed" && (
            <select value={collection} onChange={(e) => setCollection(e.target.value)}>
              <option value="">— pick indexed codebase —</option>
              {indexedCodebases.map((c) => (
                <option key={c.collection} value={c.collection}>
                  {c.label} ({c.chunks} chunks)
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* ── Advanced / governance ────────────────────────────────── */}
      <button className="sr-adv-toggle" onClick={() => setAdvOpen((o) => !o)}>
        {advOpen ? "▾" : "▸"} Advanced &amp; governance
      </button>
      {advOpen && (
        <div className="sr-adv">
          <label className="sr-check" title="Index the codebase and give every stage governed, ledger-sealed retrieval">
            <input
              type="checkbox"
              checked={ragOn}
              disabled={runType !== "govern"}
              onChange={(e) => setRagOn(e.target.checked)}
            />
            Governed RAG retrieval {runType !== "govern" && <em>(govern/enhance runs only)</em>}
          </label>
          <div className="sr-adv-row">
            <span className="sr-adv-label">RAG backend</span>
            <select
              value={ragBackend}
              disabled={!ragOn || runType !== "govern"}
              onChange={(e) => setRagBackend(e.target.value)}
            >
              <option value="auto">auto (Chroma if installed)</option>
              <option value="chroma">chroma</option>
              <option value="jsonl">jsonl (stdlib)</option>
            </select>
          </div>

          <div className="sr-adv-row">
            <span className="sr-adv-label">
              Skills that will apply
              <span className="label-hint"> — click to exclude</span>
            </span>
            <div className="sr-skills">
              {matchedSkills.length === 0 && <em>none matched yet</em>}
              {matchedSkills.map((s) => (
                <button
                  key={s.skill_id}
                  className={"sr-chip" + (excludedSkills.includes(s.skill_id) ? " off" : " on")}
                  onClick={() => toggleSkill(s.skill_id)}
                  title={excludedSkills.includes(s.skill_id) ? "Excluded — click to re-include" : s.name}
                >
                  {s.skill_id}
                </button>
              ))}
            </div>
          </div>

          <label className="sr-check">
            <input type="checkbox" checked={noVenv} onChange={(e) => setNoVenv(e.target.checked)} />
            Skip virtualenv creation
          </label>

          <div className="sr-budget" title="Hard per-run cap — a governance control, not a setting">
            Agent budget: <strong>{maxAgents}</strong> per run (fixed)
          </div>
        </div>
      )}

      {/* ── Submit ───────────────────────────────────────────────── */}
      {error && <div className="sr-error">{error}</div>}
      <button id="run-btn" disabled={starting} onClick={submit}>
        <div className={"spinner" + (starting ? " show" : "")} />
        <span>{starting ? "Starting…" : "Start governed run"}</span>
      </button>
      {activeCount > 0 && (
        <div className="parallel-hint">
          {activeCount} run{activeCount > 1 ? "s" : ""} active — this run starts in parallel
        </div>
      )}
    </div>
  );
}
