const STAGES = [
  { key: "plan", num: 1, name: "Planning", sub: "CLAUDE_PLANNER.md" },
  { key: "spec", num: 2, name: "Specification", sub: "CLAUDE_SPEC_WRITER.md" },
  { key: "env", num: 3, name: "Environment", sub: "CLAUDE_ENV_BUILDER.md · venvs/" },
  { key: "execute", num: 4, name: "Code generation", sub: "CLAUDE_EXECUTOR.md · src/" },
  { key: "test", num: 5, name: "Testing", sub: "CLAUDE_TESTER.md · tests/ · test_report.md" },
  { key: "launch", num: 6, name: "Launch app", sub: "auto-detect framework · free port" },
];

export default function StagePipeline({ stages, stageTimes }) {
  return (
    <div id="stages-section">
      <div className="section-label">Pipeline</div>
      <div className="pipeline">
        {STAGES.map((s) => (
          <div className={"stage-row " + (stages[s.key] || "")} key={s.key}>
            <div className="stage-num">{s.num}</div>
            <div className="stage-info">
              <div className="stage-name">{s.name}</div>
              <div className="stage-sub">{s.sub}</div>
            </div>
            <div className="stage-time">{stageTimes[s.key] || ""}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
