import { useEffect, useRef } from "react";

export default function EventLog({ log, onClear }) {
  const bodyRef = useRef(null);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [log.length]);

  return (
    <div id="log-section">
      <div className="log-header">
        <div className="status-dot" style={{ width: 6, height: 6 }} />
        <span className="log-header-title">Event log</span>
        <span id="log-count">{log.length} events</span>
        <span className="log-clear" onClick={onClear}>
          Clear
        </span>
      </div>
      <div id="log-body" ref={bodyRef}>
        {log.map((entry) => (
          <div className={"log-line " + entry.level} key={entry.key}>
            <span className="log-ts">{new Date(entry.ts).toLocaleTimeString("en", { hour12: false })}</span>
            <span className="log-msg" dangerouslySetInnerHTML={{ __html: entry.msg }} />
          </div>
        ))}
      </div>
    </div>
  );
}
