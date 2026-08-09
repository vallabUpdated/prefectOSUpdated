import { useEffect, useMemo, useState } from "react";

/**
 * ApprovalGateV2 — the governance heart of the product.
 *
 * Extends ApprovalGate with:
 *   • Edit / Diff tabs — the diff between what the agent proposed and what
 *     the approver changed IS the governance value; make it visible.
 *   • Approver identity — shown on the gate and sent with the decision so
 *     the ledger records WHO approved, not just that a human did.
 *   • Mandatory rejection reason (category + free text) — becomes the
 *     sealed terminal event for rejected runs.
 *   • Delegate — reassign a blocking gate to another approver.
 *
 * Decision payload (POST /approve/:runId):
 *   { decision: "approve"|"reject",
 *     edited_content: string|null,
 *     decided_by: {id, name},
 *     rejection: {category, reason}|null,
 *     delegate_to: id|null }
 */

const DOC_TITLES = {
  "planner:output": "Project Plan",
  "spec_writer:output": "Technical Specification",
};

const REJECT_CATEGORIES = [
  "Scope — not what the client asked for",
  "Risk — unacceptable technical or security risk",
  "Compliance — violates policy or regulation",
  "Quality — output below standard",
  "Duplicate / obsolete request",
  "Other",
];

/* Minimal LCS line diff — no dependency. Returns [{type: same|add|del, text}] */
function lineDiff(a, b) {
  const A = (a || "").split("\n"), B = (b || "").split("\n");
  const m = A.length, n = B.length;
  const dp = Array.from({ length: m + 1 }, () => new Uint16Array(n + 1));
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < m && j < n) {
    if (A[i] === B[j]) { out.push({ type: "same", text: A[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ type: "del", text: A[i] }); i++; }
    else { out.push({ type: "add", text: B[j] }); j++; }
  }
  while (i < m) out.push({ type: "del", text: A[i++] });
  while (j < n) out.push({ type: "add", text: B[j++] });
  return out;
}

export default function ApprovalGateV2({
  approval,           // {stage, content, editable, requested_at, agent_id}
  runId,
  currentUser,        // {id, name, role} — from auth/session
  approvers = [],     // [{id, name}] — for delegation
  onDecision,         // (payload) => Promise
}) {
  const [tab, setTab]           = useState("edit");      // edit | diff
  const [draft, setDraft]       = useState("");
  const [dirty, setDirty]       = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejCat, setRejCat]     = useState("");
  const [rejText, setRejText]   = useState("");
  const [delegateTo, setDelegateTo] = useState("");
  const [busy, setBusy]         = useState(false);
  const [err, setErr]           = useState("");

  useEffect(() => {
    setDraft(approval?.content || "");
    setDirty(false);
    setTab("edit");
    setRejecting(false);
    setRejCat("");
    setRejText("");
    setDelegateTo("");
    setErr("");
  }, [approval]);

  const editable = Boolean(approval?.editable);
  const diff = useMemo(
    () => (dirty ? lineDiff(approval?.content, draft) : []),
    [dirty, approval, draft]
  );
  const changed = diff.filter((d) => d.type !== "same").length;

  const send = async (payload) => {
    setBusy(true);
    setErr("");
    try {
      await onDecision(payload);
    } catch (e) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const approve = () =>
    send({
      decision: "approve",
      edited_content: editable && dirty ? draft : null,
      decided_by: { id: currentUser?.id, name: currentUser?.name },
      rejection: null,
      delegate_to: null,
    });

  const confirmReject = () => {
    if (!rejCat) { setErr("Pick a rejection category."); return; }
    if (rejText.trim().length < 10) {
      setErr("Give a reason (at least 10 characters) — it is sealed into the run's ledger.");
      return;
    }
    send({
      decision: "reject",
      edited_content: null,
      decided_by: { id: currentUser?.id, name: currentUser?.name },
      rejection: { category: rejCat, reason: rejText.trim() },
      delegate_to: null,
    });
  };

  const delegate = () => {
    if (!delegateTo) return;
    send({
      decision: "delegate",
      edited_content: null,
      decided_by: { id: currentUser?.id, name: currentUser?.name },
      rejection: null,
      delegate_to: delegateTo,
    });
  };

  if (!approval) return <div id="approval-gate" />;

  return (
    <div id="approval-gate" className="show">
      {/* ── Header: what + who ─────────────────────────────────── */}
      <div className="ag-header">
        <span className="ag-warn">⚠</span>
        <span className="ag-title">Approval required</span>
        <span className="ag-stage">{approval.stage}</span>
        <span className="ag-spacer" />
        <span className="ag-approver" title="Recorded in the decision ledger as decided_by">
          Deciding as <strong>{currentUser?.name || "unknown user"}</strong>
        </span>
      </div>

      {editable ? (
        <>
          <div className="ag-msg">
            Review the document. Your edits become the approved version — the
            ledger seals the exact text you approve, and the diff below is the
            record of human oversight.
          </div>

          {/* ── Edit / Diff tabs ─────────────────────────────────── */}
          <div className="ag-tabs">
            <button className={tab === "edit" ? "on" : ""} onClick={() => setTab("edit")}>
              Edit
            </button>
            <button
              className={tab === "diff" ? "on" : ""}
              onClick={() => setTab("diff")}
              disabled={!dirty}
              title={dirty ? "" : "No edits yet"}
            >
              Diff {dirty && <span className="ag-diff-count">{changed}</span>}
            </button>
          </div>

          <div className="ag-doc-page">
            <div className="ag-doc-title">
              {DOC_TITLES[approval.stage] || "Document"}
              {dirty && <span className="ag-doc-edited">edited</span>}
              {runId && (
                <a
                  className="ag-doc-download"
                  href={`/docx/${runId}/${approval.stage.startsWith("planner") ? "plan" : "spec"}`}
                  title="Download as Word document"
                >
                  ⬇ .docx
                </a>
              )}
            </div>

            {tab === "edit" ? (
              <textarea
                className="ag-doc-editor"
                value={draft}
                spellCheck={false}
                onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
              />
            ) : (
              <div className="ag-diff">
                {diff.map((d, i) => (
                  <div key={i} className={"ag-diff-line " + d.type}>
                    <span className="ag-diff-sign">
                      {d.type === "add" ? "+" : d.type === "del" ? "−" : " "}
                    </span>
                    {d.text || "\u00A0"}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : (
        <>
          <div className="ag-msg">Review the output below for stage: {approval.stage}</div>
          {approval.content && (
            <div>
              <div className="ag-file-label">Output preview</div>
              <div className="ag-preview">{approval.content}</div>
            </div>
          )}
        </>
      )}

      {/* ── Rejection form (revealed on demand) ─────────────────── */}
      {rejecting && (
        <div className="ag-reject-form">
          <div className="section-label">
            Rejection reason <span className="sr-req">sealed into the ledger</span>
          </div>
          <select value={rejCat} onChange={(e) => setRejCat(e.target.value)}>
            <option value="">— category —</option>
            {REJECT_CATEGORIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <textarea
            rows={3}
            placeholder="Why is this rejected? Written for the audit trail and for the engineer who re-runs it."
            value={rejText}
            onChange={(e) => setRejText(e.target.value)}
          />
        </div>
      )}

      {err && <div className="sr-error">{err}</div>}

      {/* ── Decision buttons ────────────────────────────────────── */}
      <div className="ag-btns">
        {!rejecting ? (
          <>
            <button className="btn-approve" disabled={busy} onClick={approve}>
              {editable && dirty ? "✓ Approve with edits" : "✓ Approve"}
            </button>
            <button className="btn-reject" disabled={busy} onClick={() => setRejecting(true)}>
              ✕ Reject…
            </button>
            <span className="ag-spacer" />
            <select
              className="ag-delegate"
              value={delegateTo}
              onChange={(e) => setDelegateTo(e.target.value)}
            >
              <option value="">Delegate to…</option>
              {approvers
                .filter((a) => a.id !== currentUser?.id)
                .map((a) => (
                  <option key={a.id} value={a.id}>{a.name}</option>
                ))}
            </select>
            {delegateTo && (
              <button className="btn-delegate" disabled={busy} onClick={delegate}>
                → Reassign
              </button>
            )}
          </>
        ) : (
          <>
            <button className="btn-reject" disabled={busy} onClick={confirmReject}>
              ✕ Confirm rejection
            </button>
            <button className="btn-back" disabled={busy} onClick={() => setRejecting(false)}>
              ← Back
            </button>
          </>
        )}
      </div>
    </div>
  );
}
