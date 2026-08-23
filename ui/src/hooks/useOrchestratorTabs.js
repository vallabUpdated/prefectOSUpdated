import { useCallback, useEffect, useState } from "react";

/**
 * useOrchestratorTabs — which optional tabs the orchestrator window shows.
 *
 * Home and Regulatory are off by default: the orchestrator's job is the live
 * run, and the two extra tabs are opt-in for operators who want them. Live run
 * is not optional — it is the window.
 *
 * State is module-level (not per-component) so the Settings dialog and the tab
 * bar agree instantly no matter which window the dialog was opened from, and
 * it is persisted so the choice survives a reload.
 */
const LS_KEY = "prefectos_orchestrator_tabs";

export const OPTIONAL_TABS = [
  { id: "home", label: "Home", hint: "Templates and the history of past pipeline runs." },
  { id: "regulatory", label: "Regulatory", hint: "Regulatory intelligence workspace." },
];

const DEFAULTS = { home: false, regulatory: false };

function read() {
  try {
    const saved = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    return {
      home: typeof saved.home === "boolean" ? saved.home : DEFAULTS.home,
      regulatory: typeof saved.regulatory === "boolean" ? saved.regulatory : DEFAULTS.regulatory,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

let state = read();
const listeners = new Set();

export function getTabPrefs() {
  return state;
}

export function setTabPrefs(next) {
  state = { ...state, ...next };
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(state));
  } catch {
    /* storage disabled — the choice just won't survive a reload */
  }
  listeners.forEach((fn) => fn());
}

export default function useOrchestratorTabs() {
  const [tabs, setTabs] = useState(state);

  useEffect(() => {
    const sync = () => setTabs(state);
    listeners.add(sync);
    sync();
    return () => listeners.delete(sync);
  }, []);

  const save = useCallback((next) => setTabPrefs(next), []);

  return { tabs, save };
}
