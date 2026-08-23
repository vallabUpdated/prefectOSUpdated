import { useState } from "react";
import LoanCard from "./LoanCard.jsx";
import useLoanJobs from "../hooks/useLoanJobs.js";
import { inr, usd, rateLabel } from "../money.js";

/**
 * AccountProcessing — the Account section of the landing page.
 *
 * Same engine as Loan Processing (two agents, per-box paths, editable prompt,
 * progress, cost, time), pointed at the account document set: statement
 * review, KYC completeness, and a free-form box for everything else.
 */
export default function AccountProcessing({ onOpenOrchestrator, bankName = "", fxRate = 0, policyPath = "" }) {
  const { boxes, config, configError, totals, actions } = useLoanJobs(bankName, "account", policyPath);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filteredBoxes = boxes.filter((box) => {
    if (filter === "active" && !["starting", "running"].includes(box.status)) return false;
    if (filter === "completed" && box.status !== "completed") return false;
    if (search.trim() && !box.label.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="lp-page">
      <header className="lp-hero">
        <div className="lp-head">
          <div className="lp-title-group">
            <div className="lp-title-row">
              <h1 className="lp-title">Account Processing Suite</h1>
              <span className="lp-tag" style={{ background: "var(--teal-soft)", color: "var(--teal)", borderColor: "var(--teal-line)" }}>
                KYC & Audit
              </span>
            </div>
            <p className="lp-sub">
              Point a box at a customer's document folder. Statement review totals financial
              periods, KYC checks ID/address documents for regulatory completeness, and general box runs custom audit prompts.
            </p>
          </div>
          <div className="lp-head-right">
            <button className="lp-liverun" onClick={onOpenOrchestrator} style={{ background: "linear-gradient(135deg, var(--teal) 0%, #0f766e 100%)", boxShadow: "0 4px 14px rgba(13, 148, 136, 0.3)" }}>
              Open Orchestrator · Live Run →
            </button>
          </div>
        </div>

        <div className="hero-stats-deck">
          <div className="hero-stat-card">
            <div className="hero-stat-head">
              <span className="hero-stat-label">Session Billed Cost (Rupees)</span>
              <span className="hero-stat-icon">💳</span>
            </div>
            <span className="hero-stat-value">{inr(totals.costUsd, fxRate)}</span>
            <span className="hero-stat-sub">
              Calculated at ₹{fxRate || 88}/USD
            </span>
          </div>

          <div className="hero-stat-card">
            <div className="hero-stat-head">
              <span className="hero-stat-label">Tokens Session Usage</span>
              <span className="hero-stat-icon">⚡</span>
            </div>
            <span className="hero-stat-value">
              {(totals.tokensIn + totals.tokensOut).toLocaleString("en-IN")}
            </span>
            <span className="hero-stat-sub">
              {totals.tokensIn.toLocaleString("en-IN")} in · {totals.tokensOut.toLocaleString("en-IN")} out
            </span>
          </div>

          <div className="hero-stat-card">
            <div className="hero-stat-head">
              <span className="hero-stat-label">Active Pipelines</span>
              <span className="hero-stat-icon">⚙️</span>
            </div>
            <span className="hero-stat-value">
              {totals.active || 0} <span style={{ fontSize: 13, fontWeight: 500, color: "var(--ink3)" }}>running</span>
            </span>
            <span className="hero-stat-sub">
              {boxes.length} total account suites initialized
            </span>
          </div>
        </div>
      </header>

      {config.model && (
        <div className="lp-meta">
          Model <code>{config.model}</code> · provider <code>{config.provider}</code>
          {config.pricing?.input_per_mtok != null && (
            <>
              {" · "}₹{(config.pricing.input_per_mtok * (fxRate || 88)).toFixed(2)} in / ₹
              {(config.pricing.output_per_mtok * (fxRate || 88)).toFixed(2)} out per million tokens
            </>
          )}
          {" · "}CSV statement exports are totalled in code; ID and address documents go to model
        </div>
      )}
      {configError && <div className="lp-error">{configError}</div>}

      <div className="lp-filter-bar">
        <div className="lp-filter-pills">
          <button
            className={"lp-filter-pill" + (filter === "all" ? " active" : "")}
            onClick={() => setFilter("all")}
          >
            All Suites ({boxes.length})
          </button>
          <button
            className={"lp-filter-pill" + (filter === "active" ? " active" : "")}
            onClick={() => setFilter("active")}
          >
            Active Runs ({totals.active || 0})
          </button>
          <button
            className={"lp-filter-pill" + (filter === "completed" ? " active" : "")}
            onClick={() => setFilter("completed")}
          >
            Completed ({boxes.filter((b) => b.status === "completed").length})
          </button>
        </div>

        <div className="lp-search-box">
          <span>🔍</span>
          <input
            type="text"
            className="lp-search-input"
            placeholder="Search account box..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      <div className="lp-grid">
        {filteredBoxes.map((box) => (
          <LoanCard key={box.loanType} box={box} actions={actions} fxRate={fxRate}
                    policyPath={policyPath} />
        ))}
      </div>
    </div>
  );
}
