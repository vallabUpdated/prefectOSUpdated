import { useEffect, useState } from "react";
import "../styles_governance.css";

/**
 * GovernancePanel — live view over /governance/*.
 * Agent roster with earned-autonomy levels, streaks and incidents;
 * per-agent + global circuit breaker; signed-receipts feed; chain
 * verification status. Levels are earned, never set — the only controls
 * here are the brakes, and even those are receipted.
 */
const LVL = {
  1: { name: "L1 observe", cls: "gv-l1" },
  2: { name: "L2 approve", cls: "gv-l2" },
  3: { name: "L3 notify", cls: "gv-l3" },
  4: { name: "L4 autonomous", cls: "gv-l4" },
};
const NEXT = { 2: 25, 3: 100 };
const EV = { call_allowed: "ok", call_gated: "gate", call_denied: "deny",
  shadow_denied: "deny", outcome: "ok", autonomy_promoted: "ok",
  autonomy_demoted: "deny", breaker_frozen: "deny", breaker_released: "ok" };

export default function GovernancePanel({ approver = "system-admin" }) {
  const [data, setData] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [verify, setVerify] = useState(null);
  const [err, setErr] = useState("");

  const refresh = () => {
    fetch("/governance/agents").then(r => r.json()).then(setData).catch(() => setErr("Governance API unreachable"));
    fetch("/governance/receipts?n=12").then(r => r.json()).then(d => setReceipts(d.receipts || [])).catch(() => {});
    fetch("/governance/verify").then(r => r.json()).then(setVerify).catch(() => {});
  };
  useEffect(() => { refresh(); const t = setInterval(refresh, 10000); return () => clearInterval(t); }, []);

  const brake = async (agent_id, freeze) => {
    setErr("");
    try {
      const r = await fetch(`/governance/${freeze ? "freeze" : "release"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_id, by: approver }),
      });
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      refresh();
    } catch (e) { setErr(String(e.message || e)); }
  };

  if (!data) return <div className="gv-wrap"><div className="gv-empty">{err || "Loading governance…"}</div></div>;

  return (
    <div className="gv-wrap">
      <div className="gv-head">
        <span className="gv-title">Agent governance</span>
        <span className={"gv-pill " + (data.shadow_mode ? "warn" : "ok")}>
          {data.shadow_mode ? "👁 shadow mode — observing only" : "● policy enforced · deny by default"}
        </span>
        {verify && (
          <span className={"gv-pill " + (verify.valid ? "ok" : "bad")}>
            {verify.valid ? "⛓ receipts signed · chain valid" : "⛓ CHAIN BROKEN — " + verify.detail}
          </span>
        )}
        <button className={"gv-brakeall" + (data.all_frozen ? " on" : "")}
          onClick={() => brake(null, !data.all_frozen)}>
          {data.all_frozen ? "▶ Release all agents" : "⏻ Freeze all agents"}
        </button>
      </div>

      {data.all_frozen && (
        <div className="gv-frozenbar">Circuit breaker engaged — every agent call is being denied and receipted.</div>
      )}
      {err && <div className="gv-err">{err}</div>}

      <div className="gv-grid">
        {data.agents.map(a => {
          const need = NEXT[a.level];
          return (
            <div key={a.agent_id} className={"gv-card" + (a.frozen || data.all_frozen ? " frozen" : "") + (a.incidents > 0 ? " incident" : "")}>
              <div className="gv-card-head">
                <span className="gv-agent">{a.agent_id}</span>
                <span className={"gv-lvl " + LVL[a.level].cls}>{LVL[a.level].name}</span>
              </div>
              <div className="gv-stats">
                {a.approved} approved · {a.rejected} rejected ·{" "}
                <span className={a.incidents ? "gv-inc" : ""}>{a.incidents} incidents</span>
              </div>
              {need ? (
                <>
                  <div className="gv-bar"><div style={{ width: Math.min(100, 100 * a.streak / need) + "%" }} /></div>
                  <div className="gv-next">{a.streak}/{need} to {LVL[a.level + 1].name}</div>
                </>
              ) : (
                <div className="gv-next">{a.level === 1 ? "ops clearance required to re-earn trust" : "highest earned level"}</div>
              )}
              <div className="gv-card-foot">
                <span className="gv-gates" title={a.always_gate.join(", ")}>
                  {a.always_gate.length ? `⚿ ${a.always_gate.length} always-gated` : "no forced gates"} · {a.allow_rules} rules
                </span>
                <button className="gv-brake" onClick={() => brake(a.agent_id, !a.frozen)}>
                  {a.frozen ? "Release" : "Freeze"}
                </button>
              </div>
              {(a.frozen || data.all_frozen) && <div className="gv-frozen-tag">FROZEN</div>}
            </div>
          );
        })}
      </div>

      <div className="gv-sub">Signed receipts — every allow, gate, deny and outcome</div>
      <div className="gv-receipts">
        {receipts.length === 0 && <div className="gv-empty">No receipts yet.</div>}
        {receipts.map(r => (
          <div key={r.receipt_id} className="gv-rec">
            <span className={"gv-ev " + (EV[r.event] || "ok")}>{r.event}</span>
            <span className="gv-rec-main">
              {r.agent_id || r.scope || ""} {r.action || ""} {r.resource || r.reason || r.outcome || ""}
              {r.approver ? ` · by ${r.approver}` : ""}{r.by ? ` · by ${r.by}` : ""}
            </span>
            <span className="gv-sig">sig {String(r.signature || "").slice(0, 6)}✓</span>
          </div>
        ))}
      </div>
    </div>
  );
}
