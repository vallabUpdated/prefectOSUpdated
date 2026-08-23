import React, { useState } from "react";

export default function RoiCalculator() {
  const [docVolume, setDocVolume] = useState(25000); // 25k docs/month
  const [manualCostPerDoc, setManualCostPerDoc] = useState(300); // ₹300 manual underwriting cost per doc

  const manualMonthly = docVolume * manualCostPerDoc;
  const prefectCostPerDoc = 25; // ₹25 governed AI cost per doc
  const prefectMonthly = docVolume * prefectCostPerDoc;

  const monthlySavings = manualMonthly - prefectMonthly;
  const annualSavings = monthlySavings * 12;
  const reductionPercent = Math.round(((manualMonthly - prefectMonthly) / manualMonthly) * 100);

  const formatRupees = (val) => {
    return "₹" + Math.round(val).toLocaleString("en-IN");
  };

  const formatLakhs = (val) => {
    if (val >= 10000000) {
      return `₹${(val / 10000000).toFixed(2)} Cr`;
    }
    if (val >= 100000) {
      return `₹${(val / 100000).toFixed(2)} Lakhs`;
    }
    return formatRupees(val);
  };

  return (
    <div className="roi-calculator-card">
      <div className="roi-header">
        <span className="section-kicker">CLIENT FINANCIAL IMPACT</span>
        <h2>Enterprise ROI &amp; Cost Reduction Calculator</h2>
        <p>Estimate your institution's annual savings in Indian Rupees (₹) by automating manual document verification with Prefect OS.</p>
      </div>

      <div className="roi-grid">
        {/* Sliders & Inputs */}
        <div className="roi-controls">
          <div className="roi-slider-group">
            <div className="roi-slider-header">
              <label>Monthly Document Volume</label>
              <span className="roi-slider-val">{docVolume.toLocaleString("en-IN")} docs / month</span>
            </div>
            <input
              type="range"
              min="1000"
              max="200000"
              step="1000"
              value={docVolume}
              onChange={(e) => setDocVolume(Number(e.target.value))}
              className="roi-slider"
            />
            <div className="roi-slider-marks">
              <span>1k</span>
              <span>50k</span>
              <span>100k</span>
              <span>200k+</span>
            </div>
          </div>

          <div className="roi-slider-group">
            <div className="roi-slider-header">
              <label>Current Manual Processing Cost per Document</label>
              <span className="roi-slider-val">₹{manualCostPerDoc} / doc</span>
            </div>
            <input
              type="range"
              min="50"
              max="1000"
              step="25"
              value={manualCostPerDoc}
              onChange={(e) => setManualCostPerDoc(Number(e.target.value))}
              className="roi-slider"
            />
            <div className="roi-slider-marks">
              <span>₹50</span>
              <span>₹500</span>
              <span>₹1,000</span>
            </div>
          </div>
        </div>

        {/* Results Cards */}
        <div className="roi-results-box">
          <div className="roi-big-stat">
            <span className="roi-stat-lbl">Estimated Annual Client Savings (₹)</span>
            <span className="roi-stat-hero">{formatRupees(annualSavings)}</span>
            <span className="roi-stat-badge">⚡ {reductionPercent}% Cost Reduction ({formatLakhs(annualSavings)}/yr)</span>
          </div>

          <div className="roi-breakdown-grid">
            <div className="roi-mini-box">
              <span className="roi-mini-lbl">Manual Monthly Cost</span>
              <span className="roi-mini-val bad">{formatLakhs(manualMonthly)}</span>
            </div>
            <div className="roi-mini-box">
              <span className="roi-mini-lbl">Prefect OS Monthly</span>
              <span className="roi-mini-val good">{formatLakhs(prefectMonthly)}</span>
            </div>
            <div className="roi-mini-box">
              <span className="roi-mini-lbl">Avg Time per Approval</span>
              <span className="roi-mini-val highlight">45 seconds</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
