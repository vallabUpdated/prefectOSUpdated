import { OPTIONAL_TABS } from "../hooks/useOrchestratorTabs.js";

const LABELS = { home: "Home", regulatory: "Regulatory", live: "Live run" };

/**
 * Tabs — the orchestrator's tab bar.
 *
 * Live run is always present; Home and Regulatory are optional and off by
 * default (Settings ▸ Orchestrator tabs). With both off the bar shows a single
 * tab, which is the point: the orchestrator opens on the run.
 */
export default function Tabs({ active, onChange, enabled = {} }) {
  const ids = [
    ...OPTIONAL_TABS.filter((t) => enabled[t.id]).map((t) => t.id),
    "live",
  ];

  return (
    <div id="tabs">
      {ids.map((id) => (
        <button key={id} className={"tab" + (active === id ? " active" : "")} onClick={() => onChange(id)}>
          {LABELS[id] || id}
        </button>
      ))}
    </div>
  );
}
