import { useState } from "react";
import LoanCard from "./LoanCard.jsx";
import useLoanJobs from "../hooks/useLoanJobs.js";
import { inr, usd, rateLabel } from "../money.js";

/**
 * LoanProcessing — the Loan section of the landing page.
 *
 * Four product boxes (Home / Vehicle / Mortgage / Personal), each processing
 * its own document set independently, plus a hand-off to the orchestrator's
 * Live run tab for work that needs the full governed pipeline.
 */
export default function LoanProcessing({ onOpenOrchestrator, bankName = "", fxRate = 0, policyPath = "" }) {
  const { boxes, config, configError, totals, actions } = useLoanJobs(bankName, "loan", policyPath);
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
              <h1 className="lp-title">Loan Processing Suite</h1>
              <span className="lp-tag">Automated Underwriting</span>
            </div>
            <p className="lp-sub">
              Point a box at an applicant's document folder. Every document is parsed and
              summarised, then assessed against that product's eligibility criteria with
              instant compliance report generation.
            </p>
          </div>
          <div className="lp-head-right">
            <button className="lp-liverun" onClick={onOpenOrchestrator}>
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
              {boxes.length} total loan products initialized
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
        </div>
      )}
      {configError && <div className="lp-error">{configError}</div>}

      <div className="lp-filter-bar">
        <div className="lp-filter-pills">
          <button
            className={"lp-filter-pill" + (filter === "all" ? " active" : "")}
            onClick={() => setFilter("all")}
          >
            All Products ({boxes.length})
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
            placeholder="Search product..."
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
