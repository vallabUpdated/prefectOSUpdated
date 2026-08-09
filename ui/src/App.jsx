import { useEffect, useState } from "react";
import usePipelineRun from "./hooks/usePipelineRun.js";
import TopBar from "./components/TopBar.jsx";
import Tabs from "./components/Tabs.jsx";
import StartRun from "./components/StartRun.jsx";
import StagePipeline from "./components/StagePipeline.jsx";
import OutputPanel from "./components/OutputPanel.jsx";
import TokenBar from "./components/TokenBar.jsx";
import AgentGrid from "./components/AgentGrid.jsx";
import ApprovalGateV2 from "./components/ApprovalGateV2.jsx";
import FilePreview from "./components/FilePreview.jsx";
import EventLog from "./components/EventLog.jsx";
import HistoryTab from "./components/HistoryTab.jsx";
import HomeTab from "./components/HomeTab.jsx";
import RunSwitcher from "./components/RunSwitcher.jsx";
import RunBoard from "./components/RunBoard.jsx";
import RegulatoryIntelligence from "./components/RegulatoryIntelligence.jsx";
import DecisionLedger from "./components/DecisionLedger.jsx";
import ComprehensionViewer from "./components/ComprehensionViewer.jsx";

export default function App() {
  const [tab, setTab] = useState("home");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftCodebase, setDraftCodebase] = useState(null); // {source, path?, git_url?, git_branch?} | null
  const [handoffNonce, setHandoffNonce] = useState(0);      // bumps on each Home → orchestrator handoff
  const [clients, setClients] = useState([]);
  const [indexedCodebases, setIndexedCodebases] = useState([]);
  const [matchedSkills, setMatchedSkills] = useState([]);
  const currentUser = {
    id: localStorage.getItem("prefectos_user_id") || "local",
    name: localStorage.getItem("prefectos_user_name") || "Local Approver",
    role: "approver",
  };

  useEffect(() => {
    fetch("/clients").then((r) => r.json()).then((d) => setClients(d.clients || [])).catch(() => { });
    fetch("/rag/collections").then((r) => r.json()).then((d) => setIndexedCodebases(d.collections || [])).catch(() => { });
  }, []);

  // Debounced live skill-match preview as the activity is typed
  useEffect(() => {
    if (!draftPrompt || draftPrompt.trim().length < 4) { setMatchedSkills([]); return; }
    const t = setTimeout(() => {
      fetch(`/skills/match?activity=${encodeURIComponent(draftPrompt)}`)
        .then((r) => r.json()).then((d) => setMatchedSkills(d.skills || [])).catch(() => { });
    }, 400);
    return () => clearTimeout(t);
  }, [draftPrompt]);

  // StartRun payload → hook (activity, codebase-path, extras)
  const startGovernedRun = (payload) => {
    const cbPath =
      payload.codebase?.source === "path" ? payload.codebase.path : "";
    const extras = { ...payload };
    delete extras.activity;
    if (cbPath) extras.codebase = undefined;        // path travels as legacy arg
    return actions.startRun(payload.activity, cbPath, extras);
  };

  // ApprovalGateV2 decision → hook
  const onGateDecision = (d) =>
    actions.sendApproval(d.decision, d.edited_content, null, {
      decided_by: d.decided_by,
      rejection: d.rejection,
    });
  const [liveView, setLiveView] = useState("detail"); // detail | board
  const { state, runs, activeRunId, activeCount, history, historyLoading, actions } = usePipelineRun();

  // Selecting a run (from the switcher or a board card) opens its detail view
  const openRunDetail = (runId) => {
    actions.selectRun(runId);
    setLiveView("detail");
  };

  useEffect(() => {
    if (tab === "history" || tab === "home") actions.loadHistory();
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectTemplate = (prompt) => {
    setTab("live");
    actions.startRun(prompt);
  };

  // Governed launch on the home tab: carry the typed prompt AND codebase
  // source over to the Live Run page (pre-filled, not auto-started) so the
  // user reviews everything at the orchestrator before starting.
  const handleCustomBuild = (prompt, codebase = null) => {
    setDraftPrompt(prompt || "");
    setDraftCodebase(codebase);
    setHandoffNonce((n) => n + 1);
    setTab("live");
  };

  const handleRegulatoryImpactRun = () => {
    const prompt = `Build a regulatory intelligence workflow for a fintech/insurance enterprise. Ingest a regulatory circular or policy update, extract obligations, map impacted applications/APIs/databases/business processes, calculate risk score, create implementation tasks, route human approvals, and generate an audit evidence pack.`;
    handleCustomBuild(prompt);
  };

  return (
    <>
      <TopBar
        status={state.status}
        statusText={state.statusText}
        runIdBadge={state.runIdBadge}
        cancelling={state.cancelling}
        paused={state.paused}
        onCancel={actions.cancelPipeline}
        onPause={actions.pausePipeline}
        onResume={actions.resumePipeline}
      />
      <Tabs active={tab} onChange={setTab} historyCount={history.length} />

      <div id="body">
        {tab === "home" && (
          <HomeTab
            history={history}
            onSelectTemplate={handleSelectTemplate}
            onSwitchTab={setTab}
            onCustomBuild={handleCustomBuild}
          />
        )}

        {tab === "live" && (
          <div id="tab-live" style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", minWidth: 0, minHeight: 0 }}>
            <RunSwitcher
              runs={runs}
              activeRunId={activeRunId}
              onSelect={openRunDetail}
              view={liveView}
              onViewChange={setLiveView}
            />
            {liveView === "board" && runs.length > 0 ? (
              <RunBoard runs={runs} actions={actions} onOpen={openRunDetail} draftPrompt={draftPrompt} />
            ) : (
              <div style={{ display: "flex", flex: 1, overflow: "hidden", minWidth: 0, minHeight: 0 }}>
                <div id="left">
                  <StartRun
                    onRun={startGovernedRun}
                    clients={clients}
                    indexedCodebases={indexedCodebases}
                    matchedSkills={matchedSkills}
                    onActivityChange={setDraftPrompt}
                    activeCount={activeCount}
                    initialActivity={draftPrompt}
                    initialCodebase={draftCodebase}
                    handoffNonce={handoffNonce}
                  />
                  <StagePipeline stages={state.stages} stageTimes={state.stageTimes} />
                  <OutputPanel output={state.output} app={state.app} onStopApp={actions.stopApp} />
                </div>

                <div id="center">
                  <TokenBar tokIn={state.tokIn} tokOut={state.tokOut} budgetUsed={state.budgetUsed} agents={state.agents} />
                  <AgentGrid agents={state.agents} />
                </div>

                <div id="right">
                  <ApprovalGateV2
                    approval={state.approval}
                    runId={state.runId}
                    currentUser={currentUser}
                    approvers={[]}
                    onDecision={onGateDecision}
                  />
                  <FilePreview filePreview={state.filePreview} />
                  <EventLog log={state.log} onClear={actions.clearLog} />
                </div>
              </div>
            )}
          </div>
        )}

        {tab === "regulatory" && <RegulatoryIntelligence onRunRegulatoryTemplate={handleRegulatoryImpactRun} />}
        {tab === "stage0" && <ComprehensionViewer />}
        {tab === "ledger" && <DecisionLedger />}
        {tab === "history" && <HistoryTab history={history} loading={historyLoading} />}
      </div>
    </>
  );
}
