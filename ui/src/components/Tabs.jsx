export default function Tabs({ active, onChange, historyCount }) {
  const tabs = [
    ["home", "Home"],
    ["regulatory", "Regulatory"],
    ["live", "Live run"],
    ["stage0", "Stage 0"],
    ["ledger", "Ledger"],
  ];

  return (
    <div id="tabs">
      {tabs.map(([id, label]) => (
        <button key={id} className={"tab" + (active === id ? " active" : "")} onClick={() => onChange(id)}>
          {label}
        </button>
      ))}
      <button className={"tab" + (active === "history" ? " active" : "")} onClick={() => onChange("history")}>
        History <span className="tab-count">{historyCount}</span>
      </button>
    </div>
  );
}
