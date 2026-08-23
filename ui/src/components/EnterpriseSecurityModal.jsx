import React from "react";

export default function EnterpriseSecurityModal({ open, onClose }) {
  if (!open) return null;

  return (
    <div className="auth-backdrop" onClick={onClose}>
      <div className="auth-modal security-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-close-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>

        <div className="sec-modal-header">
          <div className="sec-shield-icon">🛡️</div>
          <h2>Enterprise Security &amp; Compliance</h2>
          <p>Bank-grade governance, data privacy, and deterministic audit ledgers for hosted deployment.</p>
        </div>

        <div className="sec-status-banner">
          <span className="sec-status-dot" />
          <span>GLOBAL CLOUD STATUS: <strong>99.99% UPTIME SLA (OPERATIONAL)</strong></span>
        </div>

        <div className="sec-grid">
          <div className="sec-card">
            <div className="sec-card-icon">📜</div>
            <h4>SOC 2 Type II Certified</h4>
            <p>Annual third-party audit verification covering Security, Availability, and Confidentiality controls.</p>
          </div>

          <div className="sec-card">
            <div className="sec-card-icon">🔐</div>
            <h4>End-to-End Encryption</h4>
            <p>AES-256 encryption at rest, TLS 1.3 in transit with client-managed KMS encryption keys (BYOK).</p>
          </div>

          <div className="sec-card">
            <div className="sec-card-icon">🌐</div>
            <h4>Data Sovereignty &amp; Residency</h4>
            <p>Deploy in isolated VPCs across US (N. Virginia/Oregon), EU (Frankfurt/Dublin), or Asia-Pacific (Tokyo/Singapore).</p>
          </div>

          <div className="sec-card">
            <div className="sec-card-icon">⚖️</div>
            <h4>Regulatory Compliance</h4>
            <p>Built for Financial Institutions: Fannie Mae underwriting guidelines, KYC/AML, GDPR, and HIPAA compliant.</p>
          </div>
        </div>

        <div className="sec-actions">
          <a
            className="sec-btn-primary"
            href="/download/soc2-evidence-pack.pdf"
            download="PrefectOS_SOC2_TypeII_Security_Evidence_Pack.pdf"
            style={{ textDecoration: "none", display: "inline-flex", alignItems: "center", justifyContent: "center" }}
          >
            📥 Download SOC 2 Evidence Pack (.PDF)
          </a>
          <button className="sec-btn-secondary" onClick={onClose}>
            Close Window
          </button>
        </div>

        <div className="auth-footer-note">
          🔒 Zero-Data Retention Option · Deterministic Model Isolation · Hard Budget Caps
        </div>
      </div>
    </div>
  );
}
