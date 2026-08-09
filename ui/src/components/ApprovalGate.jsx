import { useEffect, useState } from "react";

const DOC_TITLES = {
  "planner:output": "Project Plan",
  "spec_writer:output": "Technical Specification",
};

export default function ApprovalGate({ approval, runId, onApprove, onReject }) {
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setDraft(approval?.content || "");
    setDirty(false);
  }, [approval]);

  const editable = Boolean(approval?.editable);

  return (
    <div id="approval-gate" className={approval ? "show" : ""}>
      {approval && (
        <>
          <div className="ag-header">
            <span className="ag-warn">⚠</span>
            <span className="ag-title">Approval required</span>
            <span className="ag-stage">{approval.stage}</span>
          </div>

          {editable ? (
            <>
              <div className="ag-msg">
                Review the document below. You can edit it directly — your changes
                become the approved version used by the next stages.
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
                <textarea
                  className="ag-doc-editor"
                  value={draft}
                  spellCheck={false}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    setDirty(true);
                  }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="ag-msg">Review the output below for stage: {approval.stage}</div>
              {approval.content ? (
                <div>
                  <div className="ag-file-label">Output preview</div>
                  <div className="ag-preview">{approval.content}</div>
                </div>
              ) : null}
            </>
          )}

          <div className="ag-btns">
            <button
              className="btn-approve"
              onClick={() => onApprove("approve", editable && dirty ? draft : null)}
            >
              {editable && dirty ? "✓ Approve with edits" : "✓ Approve"}
            </button>
            <button className="btn-reject" onClick={() => onReject("reject")}>
              ✕ Reject
            </button>
          </div>
        </>
      )}
    </div>
  );
}
