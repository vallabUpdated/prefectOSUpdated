import { useEffect, useRef } from "react";
import AuthModal from "./AuthModal.jsx";

// Where "back to the website" points: the public marketing/launch page.
// Overridable per-environment (VITE_SITE_URL) for on-prem installs.
const SITE_URL = import.meta.env?.VITE_SITE_URL || "https://www.prefectos.ai/launch.html";

/**
 * The only thing an unauthenticated visitor sees at app.prefectos.ai:
 * a clean sign-in gate. The old in-app marketing page is archived —
 * marketing, settings and workspace navigation all live on the public
 * site; this app opens directly into the workspace once the key checks
 * out.
 */
export default function AuthGate({ onAuthenticated }) {
  // AuthModal calls onClose() right after a successful onAuthenticate — a
  // close-after-success, not a cancel. Only a genuine cancel (✕ / backdrop
  // with no auth) should send the visitor back to the website.
  const authed = useRef(false);
  const handleAuthenticated = (u) => {
    authed.current = true;
    onAuthenticated(u);
  };
  const handleClose = () => {
    if (!authed.current) window.location.assign(SITE_URL);
  };
  useEffect(() => {
    // Arriving via ".../?auth=login" (the site's Login button): the gate is
    // already the sign-in, so just drop the query for a clean refresh.
    if (window.location.search) {
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
  }, []);
  return (
    <div style={{ minHeight: "100vh", background: "linear-gradient(160deg,#f7f9ff,#eef2fb)" }}>
      <div style={{ position: "absolute", top: 22, left: 28, display: "flex", gap: 10, alignItems: "center" }}>
        <img src="/prefectos-logo.png" alt="" style={{ width: 40, height: 40, borderRadius: 10, objectFit: "cover" }} />
        <b style={{ fontSize: 16, color: "#14304A" }}>Prefect OS</b>
      </div>
      <a href={SITE_URL} style={{ position: "absolute", top: 30, right: 28, fontSize: 13, color: "#5b5e78", textDecoration: "none" }}>
        ← prefectos.ai
      </a>
      <AuthModal open onClose={handleClose} onAuthenticate={handleAuthenticated} />
    </div>
  );
}
