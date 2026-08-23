import React, { useState } from "react";

const DEMO_KEYS = [
  { key: "prf_live_admin_8849", name: "Sarah Jenkins", role: "System Admin", institution: "Imperial Financial Bank" },
  { key: "prf_live_underwriter_9921", name: "David Vance", role: "Lead Underwriter", institution: "Barclays Corporate" },
  { key: "prf_live_risk_3342", name: "Elena Rostova", role: "Risk Officer", institution: "Standard Chartered" },
  { key: "prf_live_auditor_1105", name: "Marcus Vance", role: "Internal Auditor", institution: "Citigroup Commercial" },
];

export default function AuthModal({ open, onClose, onAuthenticate }) {
  const [apiKey, setApiKey] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("approver");
  const [institution, setInstitution] = useState("Imperial Financial Bank");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  React.useEffect(() => {
    if (open) {
      setError("");
    }
  }, [open]);

  if (!open) return null;

  const handleFillDemoKey = (demoObj) => {
    setApiKey(demoObj.key);
    setEmail(demoObj.name.toLowerCase().replace(" ", ".") + "@institution.com");
    setRole(demoObj.role.toLowerCase().replace(" ", "_"));
    setInstitution(demoObj.institution);
    setError("");
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");

    if (!apiKey || apiKey.trim().length < 6) {
      setError("Please enter a valid Admin-Issued Access API Key (e.g. prf_live_xxxx).");
      return;
    }

    setLoading(true);

    setTimeout(() => {
      setLoading(false);

      // Check if matches known demo key
      const matched = DEMO_KEYS.find((k) => k.key === apiKey.trim());

      const userObj = {
        id: "usr_" + Math.random().toString(36).substring(2, 9),
        name: matched ? matched.name : (email ? email.split("@")[0] : "Enterprise Licensee"),
        email: email || (matched ? `${matched.name.toLowerCase().replace(" ", ".")}@institution.com` : "licensee@institution.com"),
        institution: matched ? matched.institution : (institution || "Imperial Financial Bank"),
        role: matched ? matched.role : (role || "Approver"),
        apiKey: apiKey.trim(),
      };

      try {
        localStorage.setItem("prefectos_user_id", userObj.id);
        localStorage.setItem("prefectos_user_name", userObj.name);
        localStorage.setItem("prefectos_user_email", userObj.email);
        localStorage.setItem("prefectos_user_role", userObj.role);
        localStorage.setItem("prefectos_api_key", userObj.apiKey);
        if (userObj.institution) {
          localStorage.setItem("prefectos_bank_name", userObj.institution);
        }
      } catch {
        /* storage fallback */
      }

      onAuthenticate(userObj);
      onClose();
    }, 500);
  };

  return (
    <div className="auth-backdrop" onClick={onClose}>
      <div className="auth-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-close-btn" onClick={onClose} aria-label="Close dialog">
          ✕
        </button>

        <div className="auth-header">
          <div className="auth-brand-logo">
            <svg width="36" height="36" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
              <polygon points="50,5 90,27.5 90,72.5 50,95 10,72.5 10,27.5" fill="url(#brandGrad)" stroke="#6366f1" strokeWidth="3"/>
              <circle cx="50" cy="50" r="18" fill="#4f46e5" stroke="#38bdf8" strokeWidth="2.5"/>
              <circle cx="50" cy="50" r="7" fill="#38bdf8"/>
              <line x1="50" y1="5" x2="50" y2="32" stroke="#38bdf8" strokeWidth="2"/>
              <line x1="90" y1="27.5" x2="65.5" y2="41" stroke="#38bdf8" strokeWidth="2"/>
              <line x1="90" y1="72.5" x2="65.5" y2="59" stroke="#38bdf8" strokeWidth="2"/>
              <line x1="50" y1="95" x2="50" y2="68" stroke="#38bdf8" strokeWidth="2"/>
              <line x1="10" y1="72.5" x2="34.5" y2="59" stroke="#38bdf8" strokeWidth="2"/>
              <line x1="10" y1="27.5" x2="34.5" y2="41" stroke="#38bdf8" strokeWidth="2"/>
              <defs>
                <linearGradient id="brandGrad" x1="10" y1="5" x2="90" y2="95" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#1e1b4b"/>
                  <stop offset="1" stopColor="#0f172a"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <h2 className="auth-title">Log In to Prefect OS</h2>
          <p className="auth-subtitle">
            Enterprise access is restricted. Authentication requires an Admin-Issued License API Key.
          </p>
        </div>

        {error && <div className="auth-error-banner">⚠️ {error}</div>}

        <div className="demo-keys-section" style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 11, fontWeight: 700, color: "#64748b", textTransform: "uppercase", display: "block", marginBottom: 6 }}>
            Quick Test: Select Admin-Issued Demo API Key
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {DEMO_KEYS.map((d) => (
              <button
                key={d.key}
                type="button"
                className="sec-btn-secondary"
                onClick={() => handleFillDemoKey(d)}
                style={{ fontSize: 11, padding: "6px 8px", textAlign: "left" }}
              >
                🔑 {d.name} ({d.role})
              </button>
            ))}
          </div>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <div className="auth-field">
            <label>Admin-Issued Access API Key *</label>
            <input
              type="text"
              placeholder="e.g. prf_live_admin_8849"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required
            />
          </div>

          <div className="auth-field">
            <label>Work Email (Optional)</label>
            <input
              type="email"
              placeholder="licensee@institution.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="auth-field">
            <label>Governance Access Role</label>
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="approver">Approver / Decision Maker</option>
              <option value="lead_underwriter">Lead Underwriter</option>
              <option value="risk_officer">Risk Officer</option>
              <option value="auditor">Internal Auditor</option>
              <option value="system_admin">System Administrator</option>
            </select>
          </div>

          <button type="submit" className="auth-submit-btn" disabled={loading}>
            {loading ? "Verifying Access API Key..." : "Authenticate via Access API Key →"}
          </button>
        </form>

        <div className="auth-footer-note" style={{ marginTop: 16 }}>
          🔒 Self-registration is disabled. Contact your Prefect OS System Administrator to request an Access API Key.
        </div>
      </div>
    </div>
  );
}
