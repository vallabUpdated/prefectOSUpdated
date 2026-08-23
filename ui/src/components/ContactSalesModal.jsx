import React, { useState } from "react";

export default function ContactSalesModal({ open, onClose }) {
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [cloud, setCloud] = useState("AWS Private VPC (US / EU / APAC)");
  const [vol, setVol] = useState("50,000 – 250,000 docs / month");
  const [dispatchInfo, setDispatchInfo] = useState(null);
  const [smtpSent, setSmtpSent] = useState(false);

  if (!open) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);

    const payload = {
      recipient: "vallab@prefectos.ai",
      company,
      email,
      cloud,
      volume: vol,
    };

    try {
      const res = await fetch("/api/contact-sales", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setDispatchInfo(data.lead || payload);
      setSmtpSent(Boolean(data.smtp_sent));
    } catch {
      setDispatchInfo(payload);
      setSmtpSent(false);
    }

    setLoading(false);
    setSubmitted(true);
  };

  const handleOpenMailClient = () => {
    const subject = encodeURIComponent(`[Enterprise SLA Quote Request] ${company || " Barcays"}`);
    const body = encodeURIComponent(
      `NEW ENTERPRISE SLA QUOTE REQUEST\n\nRecipient: vallab@prefectos.ai\nInstitution / Company: ${company}\nWork Email: ${email}\nTarget Cloud: ${cloud}\nMonthly Volume: ${vol}\n\nPlease respond with custom VPC SLA terms and pricing.`
    );
    window.open(`https://mail.google.com/mail/?view=cm&fs=1&to=vallab@prefectos.ai&su=${subject}&body=${body}`, "_blank");
  };

  const handleReset = () => {
    setSubmitted(false);
    setDispatchInfo(null);
    setSmtpSent(false);
    setCompany("");
    setEmail("");
  };

  return (
    <div className="auth-backdrop" onClick={onClose}>
      <div className="auth-modal sales-modal" onClick={(e) => e.stopPropagation()}>
        <button className="auth-close-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>

        {!submitted ? (
          <>
            <div className="auth-header">
              <div className="sales-icon-box">🏢</div>
              <h2 className="auth-title">Host Prefect OS for Your Enterprise</h2>
              <p className="auth-subtitle">
                Get custom VPC deployment, dedicated 99.99% uptime SLA, and client-managed KMS encryption.
              </p>
            </div>

            <form onSubmit={handleSubmit} className="auth-form">
              <div className="auth-field">
                <label>Enterprise Institution / Company Name</label>
                <input
                  type="text"
                  placeholder="e.g. Barclays / Standard Chartered"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  required
                />
              </div>

              <div className="auth-field">
                <label>Work Email</label>
                <input
                  type="email"
                  placeholder="director@institution.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className="auth-field">
                <label>Target Cloud Deployment</label>
                <select value={cloud} onChange={(e) => setCloud(e.target.value)}>
                  <option value="AWS Private VPC (US / EU / APAC)">AWS Private VPC (US / EU / APAC)</option>
                  <option value="Microsoft Azure Confidential Cloud">Microsoft Azure Confidential Cloud</option>
                  <option value="Google Cloud Platform (GCP)">Google Cloud Platform (GCP)</option>
                  <option value="On-Premises Air-Gapped Kubernetes">On-Premises Air-Gapped Kubernetes</option>
                </select>
              </div>

              <div className="auth-field">
                <label>Estimated Monthly Document Volume</label>
                <select value={vol} onChange={(e) => setVol(e.target.value)}>
                  <option value="10,000 – 50,000 docs / month">10,000 – 50,000 docs / month</option>
                  <option value="50,000 – 250,000 docs / month">50,000 – 250,000 docs / month</option>
                  <option value="250,000 – 1,000,000 docs / month">250,000 – 1,000,000 docs / month</option>
                  <option value="1,000,000+ Enterprise Unlimited">1,000,000+ Enterprise Unlimited</option>
                </select>
              </div>

              <button type="submit" className="auth-submit-btn" disabled={loading}>
                {loading ? "Sending Quote Request..." : "Request Enterprise Custom SLA Quote →"}
              </button>
            </form>

            <div className="auth-footer-note">
              ⚡ 2-Hour Response Time · Custom SLA Terms · 14-Day Free VPC Trial Included
            </div>
          </>
        ) : (
          <div className="sales-success-view">
            <div className="sales-success-icon">{smtpSent ? "🟢" : "📧"}</div>
            <h2>
              {smtpSent
                ? "Real Email Delivered to vallab@prefectos.ai!"
                : "SLA Quote Request Logged for vallab@prefectos.ai!"}
            </h2>
            <p className="sales-success-sub">
              {smtpSent
                ? "Delivered directly via SMTP to vallab@prefectos.ai."
                : "Quote payload registered in backend dispatch log. To deliver via your Gmail inbox now, click below:"}
            </p>

            <div className="sales-summary-box">
              <div className="ss-row">
                <span>Target Email:</span>
                <strong style={{ color: "#4f46e5" }}>vallab@prefectos.ai</strong>
              </div>
              <div className="ss-row">
                <span>Institution / Company:</span>
                <strong>{dispatchInfo?.company || company}</strong>
              </div>
              <div className="ss-row">
                <span>Work Email:</span>
                <strong>{dispatchInfo?.work_email || email}</strong>
              </div>
              <div className="ss-row">
                <span>Target Deployment:</span>
                <strong>{dispatchInfo?.target_cloud || cloud}</strong>
              </div>
              <div className="ss-row">
                <span>Monthly Volume:</span>
                <strong>{dispatchInfo?.monthly_volume || vol}</strong>
              </div>
              <div className="ss-row">
                <span>SMTP Delivery Status:</span>
                <strong style={{ color: smtpSent ? "#10b981" : "#f59e0b" }}>
                  {smtpSent ? "🟢 DELIVERED VIA SMTP" : "⚠️ SMTP_PASS PENDING IN .ENV"}
                </strong>
              </div>
            </div>

            <div className="sec-actions" style={{ marginTop: 18, flexDirection: "column", gap: 10 }}>
              {!smtpSent && (
                <button
                  className="sec-btn-primary"
                  onClick={handleOpenMailClient}
                  style={{ width: "100%", background: "#4f46e5", color: "#fff" }}
                >
                  🚀 Send Direct via Gmail Compose to vallab@prefectos.ai →
                </button>
              )}
              <div style={{ display: "flex", gap: 10, width: "100%" }}>
                <button className="sec-btn-secondary" onClick={onClose} style={{ flex: 1 }}>
                  Close Window
                </button>
                <button className="sec-btn-secondary" onClick={handleReset} style={{ flex: 1 }}>
                  Send Another
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
