import { useEffect, useRef, useState } from "react";
import "../styles_chat.css";

/**
 * ChatWindow — ask the bank's own documents a question.
 *
 * A slide-over panel rather than a page: staff ask while looking at the queue
 * they are working. Every answer arrives with the clauses it came from, and a
 * question the pack does not cover is refused rather than answered from the
 * model's general knowledge (the server decides that, before spending tokens).
 */
const SUGGESTIONS = [
  "What is the maximum FOIR for a home loan?",
  "Which documents are mandatory for KYC?",
  "What LTV applies to a loan against property?",
  "How long must statements cover for a self-employed applicant?",
];

function Citation({ c }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={"cw-cite" + (open ? " open" : "")}>
      <button className="cw-cite-head" onClick={() => setOpen((v) => !v)}>
        <span className="cw-cite-src">{c.source}</span>
        <span className="cw-cite-span">[{c.span}]</span>
        <span className="cw-cite-score">{c.score}</span>
        <span className="cw-cite-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && <p className="cw-cite-preview">{c.preview}…</p>}
    </div>
  );
}

export default function ChatWindow({ open, onClose, policyPath = "", bankName = "" }) {
  const [messages, setMessages] = useState([]);   // {role, content, citations?, refused?, meta?}
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState(null);     // {ready, chunks, detail}
  const bodyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    fetch(`/chat/status?policy_path=${encodeURIComponent(policyPath)}`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ ready: false, detail: "Could not reach the server." }));
    const id = setTimeout(() => inputRef.current?.focus(), 60);
    return () => clearTimeout(id);
  }, [open, policyPath]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [messages, busy]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const ask = async (text) => {
    const question = (text ?? draft).trim();
    if (!question || busy) return;
    setDraft("");
    setBusy(true);

    // Only the plain turns travel back — citations stay client-side.
    const history = messages.map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: question }]);

    try {
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, history, policy_path: policyPath, bank_name: bankName }),
      });
      const d = await res.json();
      if (!res.ok) throw new Error(d.detail || "The request failed.");
      setMessages((prev) => [...prev, {
        role: "assistant",
        content: d.error ? `${d.answer}\n\n(${d.error})` : d.answer,
        citations: d.citations || [],
        refused: !!d.refused,
        meta: {
          tokens: (d.tokens_in || 0) + (d.tokens_out || 0),
          cost: d.cost_usd,
          ms: d.retrieve_ms,
          model: d.model,
        },
      }]);
    } catch (e) {
      setMessages((prev) => [...prev, {
        role: "assistant", content: e.message, refused: true, citations: [], error: true,
      }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cw-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="cw" role="dialog" aria-modal="true" aria-label="Ask the bank's documents">
        <header className="cw-head">
          <div className="cw-title-group">
            <span className="cw-title">Ask the policy</span>
            <span className="cw-sub">
              {status?.ready
                ? `${status.chunks} clauses indexed${status.stale ? " · pack changed since" : ""}`
                : status?.detail || "checking the document pack…"}
            </span>
          </div>
          <div className="cw-head-actions">
            {messages.length > 0 && (
              <button className="cw-clear" onClick={() => setMessages([])}>Clear</button>
            )}
            <button className="cw-close" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </header>

        <div className="cw-body" ref={bodyRef}>
          {messages.length === 0 && (
            <div className="cw-empty">
              <p className="cw-empty-lead">
                Answers come only from {bankName || "the bank"}'s indexed documents,
                with the clause behind each one. Anything they don't cover is
                declined rather than guessed at.
              </p>
              <div className="cw-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="cw-suggestion" onClick={() => ask(s)} disabled={!status?.ready}>
                    {s}
                  </button>
                ))}
              </div>
              {status && !status.ready && (
                <p className="cw-warn">
                  {status.detail || "No document pack is indexed."} Set one in
                  Settings ▸ Credit policy pack and press Index.
                </p>
              )}
            </div>
          )}

          {messages.map((m, i) => (
            <div className={"cw-msg " + m.role + (m.refused ? " refused" : "")} key={i}>
              <div className="cw-msg-text">{m.content}</div>

              {m.citations?.length > 0 && (
                <div className="cw-cites">
                  <div className="cw-cites-label">Sources</div>
                  {m.citations.map((c) => <Citation c={c} key={c.chunk_sha256 + c.span} />)}
                </div>
              )}

              {m.meta?.tokens > 0 && (
                <div className="cw-meta">
                  {m.meta.tokens.toLocaleString()} tokens
                  {m.meta.cost != null ? ` · $${Number(m.meta.cost).toFixed(4)}` : ""}
                  {m.meta.ms != null ? ` · retrieved in ${m.meta.ms} ms` : ""}
                </div>
              )}
            </div>
          ))}

          {busy && (
            <div className="cw-msg assistant">
              <div className="cw-typing"><i /><i /><i /></div>
            </div>
          )}
        </div>

        <footer className="cw-foot">
          <textarea
            ref={inputRef}
            className="cw-input"
            rows={2}
            placeholder={status?.ready ? "Ask about a policy, threshold or procedure…" : "Index a document pack first"}
            value={draft}
            disabled={!status?.ready || busy}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                ask();
              }
            }}
          />
          <button className="cw-send" onClick={() => ask()} disabled={!draft.trim() || busy || !status?.ready}>
            {busy ? "…" : "Ask"}
          </button>
        </footer>
      </aside>
    </div>
  );
}
