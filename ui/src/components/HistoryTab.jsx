export default function HistoryTab({ history, loading }) {
  if (loading && history.length === 0) {
    return (
      <div id="tab-history" style={{ display: "flex" }}>
        <div className="hist-empty">Loading…</div>
      </div>
    );
  }

  if (!history.length) {
    return (
      <div id="tab-history" style={{ display: "flex" }}>
        <div className="hist-empty">No past runs yet.</div>
      </div>
    );
  }

  return (
    <div id="tab-history" style={{ display: "flex" }}>
      <div id="hist-list">
        {history.map((r) => (
          <div className="hist-row" key={r.project_id}>
            <div className={"hist-status " + (r.status || "completed")} />
            <div className="hist-info">
              <div className="hist-id">{r.project_id || "—"}</div>
              <div className="hist-act">{r.activity || ""}</div>
            </div>
            <div className="hist-ts">{(r.created_at || "").slice(0, 16).replace("T", " ")}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
