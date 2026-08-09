const STATUS_CLASS = { ALIVE: "alive", PENDING: "pending", TORN_DOWN: "torn", FAILED: "failed" };
const BADGE_CLASS = {
  ALIVE: "badge-alive alive-pulse",
  PENDING: "badge-pending",
  TORN_DOWN: "badge-torn",
  FAILED: "badge-failed",
};
const BADGE_TEXT = { ALIVE: "🟢 Alive", PENDING: "⏳ Pending", TORN_DOWN: "⚫ Torn down", FAILED: "🔴 Failed" };

function AgentCard({ id, agent }) {
  const cls = STATUS_CLASS[agent.status] || "failed";
  const badgeCls = BADGE_CLASS[agent.status] || "badge-torn";
  const badgeTxt = BADGE_TEXT[agent.status] || agent.status;

  return (
    <div className={"agent-card " + cls}>
      <div className="ac-header">
        <div className="ac-slot">{agent.slot}</div>
        <div className="ac-id">{id}</div>
        <span className={"ac-badge " + badgeCls}>{badgeTxt}</span>
      </div>
      <div className="ac-meta">
        <div className="ac-meta-item">
          <div className="ac-meta-label">Stage</div>
          <div className="ac-meta-val">{agent.stage}</div>
        </div>
        <div className="ac-meta-item">
          <div className="ac-meta-label">Model</div>
          <div className="ac-meta-val" style={{ fontSize: 10 }}>
            {agent.model || "—"}
          </div>
        </div>
        {agent.spawned_at && (
          <div className="ac-meta-item">
            <div className="ac-meta-label">Spawned</div>
            <div className="ac-meta-val">{agent.spawned_at.slice(11, 19)}</div>
          </div>
        )}
      </div>

      {(agent.input_tokens || agent.output_tokens) ? (
        <div className="ac-tokens">
          <span className="ac-tok-in">↑ {(agent.input_tokens || 0).toLocaleString()} in</span>
          <span className="ac-tok-div">·</span>
          <span className="ac-tok-out">↓ {(agent.output_tokens || 0).toLocaleString()} out</span>
          {agent.output_chars ? (
            <>
              <span className="ac-tok-div">·</span>
              <span style={{ color: "var(--txt3)" }}>{(agent.output_chars / 1000).toFixed(1)}k chars</span>
            </>
          ) : null}
          {agent.elapsed_s ? (
            <>
              <span className="ac-tok-div">·</span>
              <span style={{ color: "var(--txt3)" }}>{agent.elapsed_s}s</span>
            </>
          ) : null}
        </div>
      ) : null}

      {agent.status === "ALIVE" && (
        <div className="ac-progress">
          <div className="ac-progress-fill" />
        </div>
      )}
    </div>
  );
}

export default function AgentGrid({ agents }) {
  const ids = Object.keys(agents).sort((a, b) => agents[a].slot - agents[b].slot);

  if (ids.length === 0) {
    return (
      <div id="agent-area">
        <div className="agent-empty">
          <div className="agent-empty-icon">⬡</div>
          <div className="agent-empty-text">Dynamic agents will appear here as they are spawned</div>
        </div>
      </div>
    );
  }

  return (
    <div id="agent-area">
      {ids.map((id) => (
        <AgentCard id={id} agent={agents[id]} key={id} />
      ))}
    </div>
  );
}
