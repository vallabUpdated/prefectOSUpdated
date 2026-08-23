/**
 * money.js — display costs in rupees.
 *
 * Anthropic bills in US dollars, so USD is the figure of record; the rupee
 * amount is a conversion at the rate the operator sets in Settings (it is not
 * a live FX feed). Both are shown so a spend can always be traced back.
 *
 * Uses en-IN grouping, so large figures read 1,23,456.78 rather than
 * 123,456.78 — the lakh/crore convention, not thousands.
 */

const INR_LARGE = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INR_SMALL = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

/** Rupees, from a USD amount at the operator's rate. */
export function inr(usd, rate) {
  if (usd == null || !Number.isFinite(rate) || rate <= 0) return "—";
  const value = usd * rate;
  // Sub-rupee spends need more than two decimals to say anything at all.
  return value > 0 && value < 1 ? INR_SMALL.format(value) : INR_LARGE.format(value);
}

/** The USD figure of record, for the sub-label. */
export function usd(value) {
  if (value == null) return "—";
  if (value === 0) return "$0.00";
  if (value >= 1) return `$${value.toFixed(2)}`;
  if (value >= 0.01) return `$${value.toFixed(3)}`;
  return `$${value.toFixed(4)}`;
}

/** "at ₹88.00/$" — the rate a figure was converted at. */
export function rateLabel(rate) {
  return Number.isFinite(rate) && rate > 0 ? `at ₹${rate.toFixed(2)}/$` : "";
}
