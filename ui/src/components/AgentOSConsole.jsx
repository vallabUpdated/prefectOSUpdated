import { useEffect, useState } from "react";
import "../styles_governance.css";
import "../styles_agentos.css";

/**
 * AgentOSConsole — two-layer Agent OS shell.
 * LAYER 1 (OS home): every industry as a tile — install state, agent
 * count, health. The OS caters for all industries at once.
 * LAYER 2 (industry workspace): one industry's agents, its own event
 * log, its controls — and its application (Banking opens the existing
 * loan/email workspace: the current product becomes Banking's app).
 * One governance spine underneath both layers; every action receipted.
 */
const EV = { call_allowed:"ok", call_gated:"gate", call_denied:"deny",
  shadow_denied:"deny", outcome:"ok", autonomy_promoted:"ok",
  autonomy_demoted:"deny", breaker_frozen:"deny", breaker_released:"ok",
  pack_activated:"ok", pack_deactivated:"deny" };
const LVL = { 1:{n:"L1 observe",c:"gv-l1"}, 2:{n:"L2 approve",c:"gv-l2"},
  3:{n:"L3 notify",c:"gv-l3"}, 4:{n:"L4 autonomous",c:"gv-l4"} };
const APP_LINKS = { banking: { label:"Open Banking workspace →",
  desc:"Loan & account document processing — this product is Banking's app on the OS" } };

export default function AgentOSConsole({ approver = "system-admin", onOpenApp }) {
  const [packs, setPacks] = useState({});
  const [agents, setAgents] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [verify, setVerify] = useState(null);
  const [ind, setInd] = useState(null);          // null = OS home (layer 1)
  const [err, setErr] = useState("");

  const refresh = () => {
    fetch("/governance/packs").then(r=>r.json()).then(d=>setPacks(d.packs||{})).catch(()=>setErr("Agent OS API unreachable"));
    fetch("/governance/agents").then(r=>r.json()).then(setAgents).catch(()=>{});
    fetch("/governance/receipts?n=40").then(r=>r.json()).then(d=>setReceipts(d.receipts||[])).catch(()=>{});
    fetch("/governance/verify").then(r=>r.json()).then(setVerify).catch(()=>{});
  };
  useEffect(()=>{ refresh(); const t=setInterval(refresh,10000); return ()=>clearInterval(t); },[]);

  const togglePack = async (name, active, ev) => {
    if (ev) ev.stopPropagation();
    setErr("");
    try {
      const r = await fetch(`/governance/packs/${name}/${active?"deactivate":"activate"}`,{
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ by: approver })});
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      refresh();
    } catch(e){ setErr(String(e.message||e)); }
  };
  const brake = async (agent_id, freeze) => {
    setErr("");
    try {
      const r = await fetch(`/governance/${freeze?"freeze":"release"}`,{
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ agent_id, by: approver })});
      if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
      refresh();
    } catch(e){ setErr(String(e.message||e)); }
  };

  const list = agents?.agents || [];
  const byDomain = d => list.filter(a=>a.domain===d);
  const agentIds = d => new Set(byDomain(d).map(a=>a.agent_id));

  // ── LAYER 2: one industry's workspace ────────────────────────────────
  if (ind && packs[ind]) {
    const p = packs[ind];
    const ags = byDomain(p.domain);
    const ids = agentIds(p.domain);
    const recs = receipts.filter(r => ids.has(r.agent_id) || r.pack === ind).slice(0, 12);
    return (
      <div className="aos-wrap">
        <div className="aos-crumb">
          <button className="aos-back" onClick={()=>setInd(null)}>← Agent OS</button>
          <span className="aos-crumb-sep">/</span>
          <span className="aos-crumb-here">{p.icon} {p.label}</span>
          {verify && <span className={"gv-pill "+(verify.valid?"ok":"bad")}>{verify.valid?"⛓ chain valid":"⛓ BROKEN"}</span>}
        </div>
        <div className="aos-ind-hero">
          <div>
            <div className="aos-ind-title">{p.label} workspace</div>
            <div className="aos-sub">{p.description} · {ags.length} governed agents</div>
          </div>
          {APP_LINKS[ind] && onOpenApp && (
            <button className="aos-app-btn" onClick={()=>onOpenApp(ind)}
              title={APP_LINKS[ind].desc}>{APP_LINKS[ind].label}</button>
          )}
        </div>
        {err && <div className="gv-err">{err}</div>}
        {!p.active && <div className="gv-frozenbar">Pack not installed — install it from the OS home to bring these agents under governance.</div>}
        <div className="gv-grid">
          {ags.map(a=>(
            <div key={a.agent_id} className={"gv-card"+(a.frozen?" frozen":"")+(a.incidents>0?" incident":"")}>
              <div className="gv-card-head">
                <span className="gv-agent">{a.agent_id}</span>
                <span className={"gv-lvl "+LVL[a.level].c}>{LVL[a.level].n}</span>
              </div>
              <div className="gv-stats">{a.approved} approved · <span className={a.incidents?"gv-inc":""}>{a.incidents} incidents</span>{a.always_gate.length?` · ⚿${a.always_gate.length} always-gated`:""}</div>
              <div className="gv-card-foot">
                <span className="gv-gates">{a.allow_rules} policy rules</span>
                <button className="gv-brake" onClick={()=>brake(a.agent_id,!a.frozen)}>{a.frozen?"Release":"Freeze"}</button>
              </div>
              {a.frozen && <div className="gv-frozen-tag">FROZEN</div>}
            </div>
          ))}
          {ags.length===0 && <div className="gv-empty">No agents yet — install the pack.</div>}
        </div>
        <div className="gv-sub">{p.label} event log — signed receipts</div>
        <div className="gv-receipts">
          {recs.length===0 && <div className="gv-empty">No activity yet in this industry.</div>}
          {recs.map(r=>(
            <div key={r.receipt_id} className="gv-rec">
              <span className={"gv-ev "+(EV[r.event]||"ok")}>{r.event}</span>
              <span className="gv-rec-main">{r.agent_id||r.pack||""} {r.action||""} {r.resource||r.reason||r.outcome||""}{r.approver?` · by ${r.approver}`:""}{r.by?` · by ${r.by}`:""}</span>
              <span className="gv-sig">sig {String(r.signature||"").slice(0,6)}✓</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── LAYER 1: OS home — all industries ────────────────────────────────
  return (
    <div className="aos-wrap">
      <div className="aos-hero">
        <div>
          <div className="aos-title">⬡ Agent OS</div>
          <div className="aos-sub">The operating system for agents. Each industry is a workspace on top of one governance spine — deny-by-default policy, earned autonomy, signed receipts, one circuit breaker.</div>
        </div>
        {verify && <span className={"gv-pill "+(verify.valid?"ok":"bad")}>{verify.valid?"⛓ chain valid":"⛓ CHAIN BROKEN"}</span>}
        {agents && <span className={"gv-pill "+(agents.shadow_mode?"warn":"ok")}>{agents.shadow_mode?"👁 shadow":"● enforcing"}</span>}
        {agents && (
          <button className={"gv-brakeall"+(agents.all_frozen?" on":"")}
            onClick={()=>brake(null,!agents.all_frozen)}>
            {agents.all_frozen?"▶ Release all":"⏻ Freeze all"}
          </button>
        )}
      </div>
      {agents?.all_frozen && <div className="gv-frozenbar">Circuit breaker engaged — every agent in every industry is denied and receipted.</div>}
      {err && <div className="gv-err">{err}</div>}

      <div className="aos-sub2">Industries on this OS — open one, or flip a switch to install</div>
      <div className="aos-tiles">
        {Object.entries(packs).map(([name,p])=>{
          const ags = byDomain(p.domain);
          const frozen = ags.filter(a=>a.frozen).length;
          const incidents = ags.reduce((n,a)=>n+a.incidents,0);
          return (
            <button key={name} className={"aos-tile"+(p.active?" active":"")} onClick={()=>setInd(name)}>
              <div className="aos-pack-head">
                <span className="aos-pack-icon">{p.icon}</span>
                <span className="aos-pack-name">{p.label}</span>
                <span className={"aos-switch"+(p.active?" on":"")} role="switch"
                  aria-checked={p.active} aria-label={`${p.label} pack`}
                  onClick={(e)=>togglePack(name,p.active,e)}>
                  <span className="aos-knob"/>
                </span>
              </div>
              <div className="aos-pack-desc">{p.description}</div>
              <div className="aos-tile-meta">
                {p.active
                  ? <>{ags.length} agents governed{incidents?<span className="gv-inc"> · {incidents} incident</span>:null}{frozen?` · ${frozen} frozen`:""}</>
                  : `${p.agents.length} agents ready to install`}
              </div>
              <div className="aos-tile-open">{p.active?"Open workspace →":"Install to open"}</div>
            </button>
          );
        })}
      </div>

      <div className="gv-sub">OS-wide event log — every industry, one signed chain</div>
      <div className="gv-receipts">
        {receipts.slice(0,8).map(r=>(
          <div key={r.receipt_id} className="gv-rec">
            <span className={"gv-ev "+(EV[r.event]||"ok")}>{r.event}</span>
            <span className="gv-rec-main">{r.pack||r.agent_id||r.scope||""} {r.action||""} {r.resource||r.reason||r.outcome||""}{r.approver?` · by ${r.approver}`:""}{r.by?` · by ${r.by}`:""}</span>
            <span className="gv-sig">sig {String(r.signature||"").slice(0,6)}✓</span>
          </div>
        ))}
      </div>
    </div>
  );
}
