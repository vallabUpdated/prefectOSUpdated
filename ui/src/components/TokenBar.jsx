import { useEffect, useRef, useState } from "react";
import { MAX_AGENTS } from "../hooks/usePipelineRun.js";

function BumpingValue({ className, value }) {
  const [bump, setBump] = useState(false);
  const prev = useRef(value);
  useEffect(() => {
    if (prev.current !== value) {
      setBump(true);
      prev.current = value;
      const id = setTimeout(() => setBump(false), 250);
      return () => clearTimeout(id);
    }
  }, [value]);
  return <span className={className + (bump ? " bump" : "")}>{value.toLocaleString()}</span>;
}

export default function TokenBar({ tokIn, tokOut, budgetUsed, agents }) {
  const activeSlotAgent = Object.values(agents).find((a) => a.slot === budgetUsed && a.status === "ALIVE");

  return (
    <div id="token-bar">
      <div className="tok-group">
        <span className="tok-label">Input</span>
        <BumpingValue className="tok-val in" value={tokIn} />
      </div>
      <div className="tok-sep">·</div>
      <div className="tok-group">
        <span className="tok-label">Output</span>
        <BumpingValue className="tok-val out" value={tokOut} />
      </div>
      <div className="tok-sep">·</div>
      <div className="tok-group">
        <span className="tok-label">Total tokens</span>
        <BumpingValue className="tok-val tot" value={tokIn + tokOut} />
      </div>
      <div id="budget-group">
        <span className="budget-label">Budget</span>
        <div id="budget-pips">
          {Array.from({ length: MAX_AGENTS }, (_, i) => {
            let cls = "pip";
            if (i < budgetUsed) cls += i === budgetUsed - 1 && activeSlotAgent ? " active" : " used";
            return <div className={cls} key={i} />;
          })}
        </div>
        <span id="budget-txt">
          {budgetUsed} / {MAX_AGENTS}
        </span>
      </div>
    </div>
  );
}
