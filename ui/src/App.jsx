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
import HomeTab from "./components/HomeTab.jsx";
import RunSwitcher from "./components/RunSwitcher.jsx";
import RunBoard from "./components/RunBoard.jsx";
import RegulatoryIntelligence from "./components/RegulatoryIntelligence.jsx";
import LandingPage from "./components/LandingPage.jsx";
import ProcessingWindow from "./components/ProcessingWindow.jsx";
import DocJobRun from "./components/DocJobRun.jsx";
import useDocJobRuns from "./hooks/useDocJobRuns.js";
import { cancel as cancelDocJob } from "./loanJobStore.js";
import useOrchestratorTabs from "./hooks/useOrchestratorTabs.js";
import useInstitutionSettings from "./hooks/useInstitutionSettings.js";
import SettingsDialog from "./components/SettingsDialog.jsx";

export default function App() {
  const [view, setView] = useState("landing"); // landing | processing | orchestrator
  const [tab, setTab] = useState("live");
  const [draftPrompt, setDraftPrompt] = useState("");
  const [draftCodebase, setDraftCodebase] = useState(null); // {source, path?, git_url?, git_branch?} | null
  const [handoffNonce, setHandoffNonce] = useState(0);      // bumps on each Home → orchestrator handoff
  const [clients, setClients] = useState([]);
  const [indexedCodebases, setIndexedCodebases] = useState([]);
  const [matchedSkills, setMatchedSkills] = useState([]);
  const [currentUser, setCurrentUser] = useState(() => ({
    id: localStorage.getItem("prefectos_user_id") || "local",
    name: localStorage.getItem("prefectos_user_name") || "Local Approver",
    email: localStorage.getItem("prefectos_user_email") || "approver@bank.com",
    role: localStorage.getItem("prefectos_user_role") || "approver",
  }));

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
  const { state, runs, activeRunId, activeCount, history, actions } = usePipelineRun();

  // Document jobs running anywhere in the app — synced via useDocJobRuns
  const docRuns = useDocJobRuns();
  const [selectedDocRunId, setSelectedDocRunId] = useState(null);
  const selectedDocRun =
    docRuns.find((r) => r.runId === selectedDocRunId) || null;

  const PIPELINE_CHIP = "__pipeline__";

  const handleSelectRun = (runId) => {
    if (runId.startsWith("doc_")) {
      setSelectedDocRunId(runId);
    } else {
      setSelectedDocRunId(null);
      if (runId !== PIPELINE_CHIP) actions.selectRun(runId);
    }
    setLiveView("detail");
  };

  const openLiveRun = (domain = null) => {
    const mine = domain ? docRuns.filter((r) => r.domain === domain) : docRuns;
    const pool = mine.length ? mine : docRuns;
    const latest = pool[pool.length - 1];
    if (latest && (latest.running || !activeRunId)) {
      setSelectedDocRunId(latest.runId);
    } else {
      setSelectedDocRunId(null);
    }
    setTab("live");
    setLiveView("detail");
  };

  useEffect(() => {
    if (tab === "home") actions.loadHistory();
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSelectTemplate = (prompt) => {
    setSelectedDocRunId(null);
    setTab("live");
    actions.startRun(prompt);
  };

  const handleCustomBuild = (prompt, codebase = null) => {
    setSelectedDocRunId(null);
    setDraftPrompt(prompt || "");
    setDraftCodebase(codebase);
    setHandoffNonce((n) => n + 1);
    setTab("live");
  };

  const handleRegulatoryImpactRun = () => {
    const prompt = `Build a regulatory intelligence workflow for a fintech/insurance enterprise. Ingest a regulatory circular or policy update, extract obligations, map impacted applications/APIs/databases/business processes, calculate risk score, create implementation tasks, route human approvals, and generate an audit evidence pack.`;
    handleCustomBuild(prompt);
  };

  const tabPrefs = useOrchestratorTabs();
  const institution = useInstitutionSettings();
  const [settingsOpen, setSettingsOpen] = useState(false);

  const openOrchestratorHub = (prompt = null) => {
    if (prompt && typeof prompt === "string") {
      setDraftPrompt(prompt);
      setHandoffNonce((n) => n + 1);
    }
    setSelectedDocRunId(null);
    setTab("live");
    setView("orchestrator");
  };

  // The processing workspace is licensed: signing out (or arriving without a
  // session) sends you back to the landing page rather than into the suites.
  const signedIn = !!(currentUser && currentUser.id && currentUser.id !== "local");

  if (view === "landing" || (view === "processing" && !signedIn)) {
    return (
      <LandingPage
        onOpenOrchestrator={openOrchestratorHub}
        onOpenProcessing={() => setView("processing")}
        currentUser={currentUser}
        onUserUpdate={setCurrentUser}
      />
    );
  }

  if (view === "processing") {
    return (
      <ProcessingWindow
        onBack={() => setView("landing")}
        currentUser={currentUser}
        onOpenOrchestrator={(domain) => {
          openLiveRun(typeof domain === "string" ? domain : null);
          setView("orchestrator");
        }}
      />
    );
  }

  return (
    <>
      <TopBar
        status={selectedDocRun ? selectedDocRun.status : state.status}
        statusText={selectedDocRun ? selectedDocRun.statusText : state.statusText}
        runIdBadge={selectedDocRun ? selectedDocRun.jobId || selectedDocRun.chipName : state.runIdBadge}
        cancelling={selectedDocRun ? false : state.cancelling}
        paused={selectedDocRun ? false : state.paused}
        onCancel={selectedDocRun
          ? () => cancelDocJob(selectedDocRun.domain, selectedDocRun.loanType)
          : actions.cancelPipeline}
        onPause={selectedDocRun ? null : actions.pausePipeline}
        onResume={selectedDocRun ? null : actions.resumePipeline}
        // "← Processing" goes back to the Processing Status page, the window
        // the orchestrator is entered from (the landing page is behind that).
        onBack={() => setView("processing")}
        onSettings={() => setSettingsOpen(true)}
      />
      <Tabs active={tab} onChange={setTab} enabled={tabPrefs} />

      <SettingsDialog
        open={settingsOpen}
        bankName={institution.bankName}
        fxRate={institution.fxRate}
        policyPath={institution.policyPath}
        onSave={institution.save}
        onClose={() => setSettingsOpen(false)}
      />

      <div id="body">
        {tab === "home" && (
          <HomeTab
            history={history}
            onSelectTemplate={handleSelectTemplate}
            onCustomBuild={handleCustomBuild}
          />
        )}

        {tab === "live" && (
          <div id="tab-live" style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden", minWidth: 0, minHeight: 0 }}>
            <RunSwitcher
              runs={runs}
              activeRunId={activeRunId}
              onSelect={handleSelectRun}
              view={liveView}
              onViewChange={setLiveView}
              docRuns={docRuns}
              activeDocRunId={selectedDocRunId}
            />
            {liveView === "board" && runs.length > 0 ? (
              <RunBoard runs={runs} actions={actions} onOpen={handleSelectRun} draftPrompt={draftPrompt} />
            ) : selectedDocRun ? (
              <DocJobRun job={selectedDocRun} />
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
      </div>
    </>
  );
}
