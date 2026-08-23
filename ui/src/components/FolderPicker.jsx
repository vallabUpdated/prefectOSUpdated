import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import "../styles_folderpicker.css";

/**
 * FolderPicker — pick a real path on the machine running the server.
 *
 * A browser file input deliberately hides the true path, and the backend needs
 * one it can actually open, so the walk happens server-side via /loan/browse
 * and nothing is uploaded or copied.
 *
 * mode "input"  — pick a folder of documents, or a single document
 * mode "output" — pick (or create) a destination folder
 */
export default function FolderPicker({ open, mode = "input", startPath = "", onPick, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [newFolder, setNewFolder] = useState("");

  const load = useCallback((path, { fallback = false } = {}) => {
    setLoading(true);
    setError("");
    setSelectedFile(null);
    fetch(`/loan/browse?path=${encodeURIComponent(path || "")}`)
      .then(async (r) => ({ ok: r.ok, d: await r.json() }))
      .then(({ ok, d }) => {
        if (ok) {
          setData(d);
          return;
        }
        setError(d.detail || "Could not open that folder.");
        if (d.shortcuts) setData((prev) => prev || { ...d, dirs: [], files: [] });
        // A saved path that no longer resolves would otherwise leave the picker
        // with nothing to browse. Drop back to the default listing, once.
        if (fallback && path) load("");
      })
      .catch(() => setError("The server could not be reached."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (open) load(startPath, { fallback: true });
  }, [open, startPath, load]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const sep = data?.separator || "\\";
  const crumbs = [];
  if (data?.path) {
    const parts = data.path.split(/[\\/]+/).filter(Boolean);
    let acc = data.path.startsWith("/") ? "" : null;
    parts.forEach((part, i) => {
      acc = acc === null ? part + sep : `${acc}${sep}${part}`;
      crumbs.push({ label: part, path: i === 0 && sep === "\\" ? part + sep : acc });
    });
  }

  const createFolder = () => {
    if (!newFolder.trim()) return;
    fetch("/loan/mkdir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: data.path, name: newFolder.trim() }),
    })
      .then(async (r) => ({ ok: r.ok, d: await r.json() }))
      .then(({ ok, d }) => {
        if (!ok) return setError(d.detail || "Could not create the folder.");
        setNewFolder("");
        load(d.path);
      })
      .catch(() => setError("Could not create the folder."));
  };

  // Rendered into <body>, not where it is written. The cards this picker opens
  // from lift on hover (transform), and a transformed ancestor becomes the
  // containing block for position:fixed — which anchored the dialog to the card
  // and made it jump as the pointer moved on and off it.
  return createPortal(
    <div className="pk-backdrop" role="dialog" aria-modal="true" aria-label="Choose a location"
         onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pk">
        <header className="pk-head">
          <div className="pk-title">
            {mode === "output" ? "Choose an output folder" : "Choose documents"}
          </div>
          <button className="pk-close" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <div className="pk-body">
          <aside className="pk-side">
            <div className="pk-side-label">Places</div>
            {(data?.shortcuts || []).map((s) => (
              <button key={s.path} className="pk-side-item" onClick={() => load(s.path)}>
                {s.name}
              </button>
            ))}
            <div className="pk-side-label">Drives</div>
            {(data?.drives || []).map((d) => (
              <button key={d.path} className="pk-side-item mono" onClick={() => load(d.path)}>
                {d.name}
              </button>
            ))}
          </aside>

          <main className="pk-main">
            <div className="pk-crumbs">
              {data?.parent != null && (
                <button className="pk-up" onClick={() => load(data.parent)} title="Up one level">
                  ↑
                </button>
              )}
              {crumbs.map((c, i) => (
                <span key={c.path + i}>
                  <button className="pk-crumb" onClick={() => load(c.path)}>{c.label}</button>
                  {i < crumbs.length - 1 && <span className="pk-crumb-sep">{sep}</span>}
                </span>
              ))}
            </div>

            {error && <div className="pk-error">{error}</div>}

            <div className="pk-list">
              {loading && <div className="pk-empty">Loading…</div>}
              {!loading && data && (data.dirs || []).length === 0 &&
                (data.files || []).length === 0 && (
                  <div className="pk-empty">This folder is empty.</div>
                )}
              {!loading && (data?.dirs || []).map((d) => (
                <button key={d.path} className="pk-row pk-dir" onDoubleClick={() => load(d.path)}
                        onClick={() => load(d.path)}>
                  <span className="pk-icon">▸</span>
                  <span className="pk-name">{d.name}</span>
                </button>
              ))}
              {!loading && mode === "input" && (data?.files || []).map((f) => (
                <button
                  key={f.path}
                  className={"pk-row pk-file" + (f.supported ? "" : " unsupported")
                    + (selectedFile === f.path ? " selected" : "")}
                  onClick={() => f.supported && setSelectedFile(f.path)}
                  disabled={!f.supported}
                  title={f.supported ? "Process this single document" : "Unsupported file type"}
                >
                  <span className="pk-icon">·</span>
                  <span className="pk-name">{f.name}</span>
                  <span className="pk-size">{(f.size / 1024).toFixed(0)} KB</span>
                </button>
              ))}
            </div>

            <div className="pk-foot-note">
              {mode === "input" && data
                ? `${data.processable ?? 0} processable document${(data.processable ?? 0) === 1 ? "" : "s"} in this folder`
                : "Reports are written into the folder you choose."}
            </div>
          </main>
        </div>

        <footer className="pk-foot">
          {mode === "output" && (
            <div className="pk-newfolder">
              <input
                className="pk-input"
                placeholder="New folder name"
                value={newFolder}
                onChange={(e) => setNewFolder(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && createFolder()}
              />
              <button className="pk-btn" onClick={createFolder} disabled={!newFolder.trim()}>
                Create
              </button>
            </div>
          )}
          <div className="pk-selected mono">{selectedFile || data?.path || ""}</div>
          <button className="pk-btn" onClick={onClose}>Cancel</button>
          <button
            className="pk-btn pk-btn-primary"
            disabled={!data?.path}
            onClick={() => { onPick(selectedFile || data.path); onClose(); }}
          >
            {selectedFile ? "Use this file" : "Use this folder"}
          </button>
        </footer>
      </div>
    </div>,
    document.body
  );
}
