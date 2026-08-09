export default function AppPanel({ app, onStop }) {
  if (!app.show) return <div className="app-panel" />;

  const cls = "app-panel show " + (app.running ? "running" : "stopped");
  const title = app.running
    ? `${(app.framework || "app").charAt(0).toUpperCase()}${(app.framework || "app").slice(1)} app running`
    : "App stopped";

  return (
    <div className={cls}>
      <div className="app-header">
        <span className="app-icon">{app.running ? "▶" : "■"}</span>
        <span className="app-title">{title}</span>
        <span style={{ marginLeft: "auto", fontSize: 10, fontFamily: "var(--mono)", color: "var(--txt3)" }}>
          {app.running ? "LIVE" : "stopped"}
        </span>
      </div>
      <div className="app-url-row">
        <div className="app-url">
          {app.url && app.running ? (
            <a href={app.url} target="_blank" rel="noreferrer">
              {app.url}
            </a>
          ) : (
            app.url || "—"
          )}
        </div>
      </div>
      <div className="app-meta-grid">
        <div className="app-meta-card">
          <div className="app-meta-label">Framework</div>
          <div className="app-meta-val">{app.framework || "—"}</div>
        </div>
        <div className="app-meta-card">
          <div className="app-meta-label">Port</div>
          <div className="app-meta-val">{app.port || "—"}</div>
        </div>
        <div className="app-meta-card">
          <div className="app-meta-label">PID</div>
          <div className="app-meta-val">{app.pid || "—"}</div>
        </div>
        <div className="app-meta-card">
          <div className="app-meta-label">Command</div>
          <div className="app-meta-val" style={{ fontSize: 9, wordBreak: "break-all" }}>
            {app.cmd || "—"}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        {app.running && app.url && (
          <a className="btn-open" href={app.url} target="_blank" rel="noreferrer">
            ↗ Open app
          </a>
        )}
        {app.running && app.pid ? (
          <button className="btn-stop" onClick={onStop}>
            ■ Stop
          </button>
        ) : (
          <span style={{ fontSize: 11, color: "var(--txt3)" }}>Process stopped</span>
        )}
      </div>
    </div>
  );
}
