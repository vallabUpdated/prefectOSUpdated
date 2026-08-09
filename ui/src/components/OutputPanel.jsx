import AppPanel from "./AppPanel.jsx";

export default function OutputPanel({ output, app, onStopApp }) {
  return (
    <div id="venv-section">
      <div className="section-label">Project output</div>
      <div id="venv-info">
        <div className="venv-row">
          <span className="venv-key">Project</span>
          <span className="venv-val">{output.project || "—"}</span>
        </div>
        <div className="venv-row">
          <span className="venv-key">Venv</span>
          <span className="venv-val">{output.venv || "—"}</span>
        </div>
        <div className="venv-row">
          <span className="venv-key">Files</span>
          <span className="venv-val">{output.files && output.files.length ? output.files.join(", ") : "—"}</span>
        </div>
      </div>
      <AppPanel app={app} onStop={onStopApp} />
    </div>
  );
}
