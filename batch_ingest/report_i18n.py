# Part of the PrefectOS core package — batch_ingest.
"""English ⇄ ಕನ್ನಡ for the generated HTML reports.

Every fixed label in a report is written in both languages, side by side:

    <span class="l-en">Applicant file</span><span class="l-kn" lang="kn">ಅರ್ಜಿದಾರರ ಕಡತ</span>

and CSS shows one or the other depending on <html lang>. The switch in the
report's top-right corner only flips that attribute, so:

  - the file stays 100% self-contained (inline CSS/JS, system fonts, no network);
  - with scripts disabled (e-mail clients, strict viewers) it reads in English;
  - printing produces whichever language is on screen;
  - nothing about the sealed JSON, its SHA-256 or the ledger changes — the
    language is presentation only.

The language follows the reader: ?lang=kn on the URL, else the choice made on
the website / workspace (localStorage "prefectos_lang"), else English.

What is translated: headings, field names, table headers, status words and
stamps — the vocabulary in KN below. What is NOT translated: anything the
agents wrote or quoted (findings, evidence, rationale, document facts), names,
figures, file paths and hashes. Those are the record; the Kannada view says so
in a note under the header.

To change wording, edit the right-hand side of KN. A label with no entry in KN
is rendered in English only.
"""
from __future__ import annotations

import html

KN: dict[str, str] = {
    # ── shared ───────────────────────────────────────────────────────────────
    "Processing report": "ಸಂಸ್ಕರಣಾ ವರದಿ",
    "processing report": "ಸಂಸ್ಕರಣಾ ವರದಿ",
    "Eligibility report": "ಅರ್ಹತಾ ವರದಿ",
    "eligibility report": "ಅರ್ಹತಾ ವರದಿ",
    "Generated": "ರಚನೆ:",
    "Processed in": "ಸಂಸ್ಕರಣಾ ಅವಧಿ:",
    "Job": "ಜಾಬ್",
    "Batch": "ಬ್ಯಾಚ್",
    "Status": "ಸ್ಥಿತಿ",
    "Type": "ಪ್ರಕಾರ",
    "Check": "ಪರಿಶೀಲನೆ",

    # ── loan / account eligibility report ────────────────────────────────────
    "Governed loan document processing": "ನಿಯಂತ್ರಿತ ಸಾಲ ದಾಖಲೆ ಸಂಸ್ಕರಣೆ",
    "Decision": "ನಿರ್ಧಾರ",
    "Outcome": "ಫಲಿತಾಂಶ",
    # stamps and verdict codes
    "ELIGIBLE": "ಅರ್ಹ",
    "NOT ELIGIBLE": "ಅನರ್ಹ",
    "NOT_ELIGIBLE": "ಅನರ್ಹ",
    "NEEDS REVIEW": "ಪರಿಶೀಲನೆ ಅಗತ್ಯ",
    "NEEDS_REVIEW": "ಪರಿಶೀಲನೆ ಅಗತ್ಯ",
    "COMPLETE": "ಪೂರ್ಣ",
    "INCOMPLETE": "ಅಪೂರ್ಣ",
    "REPORTED": "ವರದಿ ಮಾಡಲಾಗಿದೆ",
    "NO DECISION": "ನಿರ್ಧಾರವಿಲ್ಲ",
    "All criteria evidenced by the file": "ಎಲ್ಲ ಮಾನದಂಡಗಳಿಗೂ ಕಡತದಲ್ಲಿ ಸಾಕ್ಷ್ಯವಿದೆ",
    "A criterion is breached on the evidence": "ಸಾಕ್ಷ್ಯದ ಪ್ರಕಾರ ಒಂದು ಮಾನದಂಡ ಉಲ್ಲಂಘನೆಯಾಗಿದೆ",
    "Criteria unverified — human review required": "ಮಾನದಂಡಗಳು ಪರಿಶೀಲನೆಯಾಗಿಲ್ಲ — ಮಾನವ ಪರಿಶೀಲನೆ ಅಗತ್ಯ",
    "Every required item is present and valid": "ಅಗತ್ಯವಿರುವ ಪ್ರತಿಯೊಂದು ಅಂಶವೂ ಇದೆ ಮತ್ತು ಮಾನ್ಯವಾಗಿದೆ",
    "Required items are missing or expired": "ಅಗತ್ಯ ಅಂಶಗಳು ಕಾಣೆಯಾಗಿವೆ ಅಥವಾ ಅವಧಿ ಮೀರಿವೆ",
    "Figures reported from the documents supplied": "ಸಲ್ಲಿಸಿದ ದಾಖಲೆಗಳಿಂದ ಅಂಕಿಅಂಶಗಳನ್ನು ವರದಿ ಮಾಡಲಾಗಿದೆ",
    "No structured decision was returned": "ರಚನಾತ್ಮಕ ನಿರ್ಧಾರ ಲಭ್ಯವಾಗಿಲ್ಲ",
    # applicant file
    "Applicant file": "ಅರ್ಜಿದಾರರ ಕಡತ",
    "Loan product": "ಸಾಲ ಉತ್ಪನ್ನ",
    "Applicant": "ಅರ್ಜಿದಾರ",
    "Confidence": "ವಿಶ್ವಾಸ ಮಟ್ಟ",
    "high": "ಹೆಚ್ಚು", "medium": "ಮಧ್ಯಮ", "low": "ಕಡಿಮೆ",
    "High": "ಹೆಚ್ಚು", "Medium": "ಮಧ್ಯಮ", "Low": "ಕಡಿಮೆ",
    "Documents": "ದಾಖಲೆಗಳು",
    "processed": "ಸಂಸ್ಕರಿಸಲಾಗಿದೆ",
    "unreadable": "ಓದಲಾಗದವು",
    "Agents": "ಏಜೆಂಟ್‌ಗಳು",
    "Model": "ಮಾದರಿ",
    "Processing time": "ಸಂಸ್ಕರಣಾ ಸಮಯ",
    "Per document": "ಪ್ರತಿ ದಾಖಲೆಗೆ",
    "average": "ಸರಾಸರಿ",
    "Input path": "ಇನ್‌ಪುಟ್ ಪಥ",
    # verdict strip
    "Checks met": "ಪೂರೈಸಿದ ಪರಿಶೀಲನೆಗಳು",
    "Missing documents": "ಕಾಣೆಯಾದ ದಾಖಲೆಗಳು",
    "Risk flags": "ಅಪಾಯ ಸೂಚನೆಗಳು",
    "Next steps": "ಮುಂದಿನ ಹಂತಗಳು",
    "No rationale was returned.": "ಯಾವುದೇ ತಾರ್ಕಿಕ ವಿವರಣೆ ಲಭ್ಯವಾಗಿಲ್ಲ.",
    # criteria / findings
    "Checks": "ಪರಿಶೀಲನೆಗಳು",
    "Eligibility criteria": "ಅರ್ಹತಾ ಮಾನದಂಡಗಳು",
    "Criterion": "ಮಾನದಂಡ",
    "Evidence": "ಸಾಕ್ಷ್ಯ",
    "✓ met": "✓ ಪೂರೈಸಿದೆ",
    "✗ not met": "✗ ಪೂರೈಸಿಲ್ಲ",
    "◦ unverified": "◦ ಪರಿಶೀಲನೆಯಾಗಿಲ್ಲ",
    "met": "ಪೂರೈಸಿದೆ",
    "not_met": "ಪೂರೈಸಿಲ್ಲ",
    "unverified": "ಪರಿಶೀಲನೆಯಾಗಿಲ್ಲ",
    "Findings": "ಕಂಡುಬಂದ ಅಂಶಗಳು",
    "Item": "ಅಂಶ",
    "Value": "ಮೌಲ್ಯ",
    "Basis": "ಆಧಾರ",
    # documents
    "Documents processed": "ಸಂಸ್ಕರಿಸಿದ ದಾಖಲೆಗಳು",
    "Document": "ದಾಖಲೆ",
    "Relevance": "ಪ್ರಸ್ತುತತೆ",
    "Key facts": "ಪ್ರಮುಖ ಅಂಶಗಳು",
    # plan
    "Processing plan · Planning Agent": "ಸಂಸ್ಕರಣಾ ಯೋಜನೆ · ಯೋಜನಾ ಏಜೆಂಟ್",
    "Watch-for signals": "ಗಮನಿಸಬೇಕಾದ ಸೂಚನೆಗಳು",
    "Expected but absent": "ನಿರೀಕ್ಷಿತ, ಆದರೆ ಲಭ್ಯವಿಲ್ಲ",
    # policy
    "Policy thresholds applied in code ({0} of {1} decided)":
        "ಕೋಡ್‌ನಲ್ಲಿ ಅನ್ವಯಿಸಿದ ನೀತಿ ಮಿತಿಗಳು ({1} ರಲ್ಲಿ {0} ನಿರ್ಧರಿತ)",
    "Bands selected from the policy and compared against the parsed figures by the pipeline — "
    "no model arithmetic. The agent was given these as settled.":
        "ನೀತಿಯಿಂದ ಆಯ್ದ ಶ್ರೇಣಿಗಳನ್ನು ಪೈಪ್‌ಲೈನ್ ಸ್ವತಃ ಪಾರ್ಸ್ ಮಾಡಿದ ಅಂಕಿಗಳೊಂದಿಗೆ ಹೋಲಿಸಿದೆ — "
        "ಮಾದರಿಯ ಲೆಕ್ಕಾಚಾರವಿಲ್ಲ. ಇವುಗಳನ್ನು ಏಜೆಂಟ್‌ಗೆ ಅಂತಿಮವೆಂದು ನೀಡಲಾಗಿದೆ.",
    "Clause": "ಖಂಡ",
    "Credit policy retrieved ({0} clauses)": "ಪಡೆದ ಸಾಲ ನೀತಿ ({0} ಖಂಡಗಳು)",
    "Retrieved from the bank's policy pack and supplied to the Processing Agent for this "
    "assessment — {0} clauses in the pack, {1} ms, query":
        "ಈ ಮೌಲ್ಯಮಾಪನಕ್ಕಾಗಿ ಬ್ಯಾಂಕಿನ ನೀತಿ ಪ್ಯಾಕ್‌ನಿಂದ ಪಡೆದು ಸಂಸ್ಕರಣಾ ಏಜೆಂಟ್‌ಗೆ ಒದಗಿಸಲಾಗಿದೆ — "
        "ಪ್ಯಾಕ್‌ನಲ್ಲಿ {0} ಖಂಡಗಳು, {1} ms, ಕ್ವೆರಿ",
    "Source": "ಮೂಲ",
    "Opening": "ಆರಂಭಿಕ ಪಠ್ಯ",
    "Score": "ಅಂಕ",
    # agents
    "Agents ({0} of {1})": "ಏಜೆಂಟ್‌ಗಳು ({1} ರಲ್ಲಿ {0})",
    "Agent": "ಏಜೆಂಟ್",
    "Role": "ಪಾತ್ರ",
    "Role card": "ಪಾತ್ರ ಕಾರ್ಡ್",
    "Calls": "ಕರೆಗಳು",
    # footer
    "For internal credit review only.": "ಆಂತರಿಕ ಸಾಲ ಪರಿಶೀಲನೆಗೆ ಮಾತ್ರ.",
    "generated": "ರಚನೆ:",
    "Report SHA-256:": "ವರದಿ SHA-256:",
    "Written to {0} alongside {1}, {2} and the per-document findings under {3}. This report is "
    "generated deterministically from the sealed JSON — regenerate it at any time from that file.":
        "{0} ನಲ್ಲಿ ಬರೆಯಲಾಗಿದೆ; ಜೊತೆಗೆ {1}, {2} ಮತ್ತು ಪ್ರತಿ ದಾಖಲೆಯ ಫಲಿತಾಂಶಗಳು {3} ಅಡಿಯಲ್ಲಿವೆ. ಈ ವರದಿಯನ್ನು "
        "ಮುದ್ರೆಯೊತ್ತಿದ JSON ನಿಂದ ನಿರ್ಧಾರಾತ್ಮಕವಾಗಿ ರಚಿಸಲಾಗಿದೆ — ಆ ಕಡತದಿಂದ ಯಾವಾಗ ಬೇಕಾದರೂ ಮರುರಚಿಸಬಹುದು.",

    # ── batch statement processing report ────────────────────────────────────
    "Governed document processing": "ನಿಯಂತ್ರಿತ ದಾಖಲೆ ಸಂಸ್ಕರಣೆ",
    "VERIFIED": "ಪರಿಶೀಲಿಸಲಾಗಿದೆ",
    "Deterministic checks passed — no AI used": "ನಿರ್ಧಾರಾತ್ಮಕ ಪರಿಶೀಲನೆಗಳು ಯಶಸ್ವಿ — AI ಬಳಸಿಲ್ಲ",
    "AI-REPAIRED": "AI ಸರಿಪಡಿಸಿದೆ",
    "Flagged rows repaired by governed AI call": "ಗುರುತಿಸಿದ ಸಾಲುಗಳನ್ನು ನಿಯಂತ್ರಿತ AI ಕರೆ ಸರಿಪಡಿಸಿದೆ",
    "HUMAN REVIEW": "ಮಾನವ ಪರಿಶೀಲನೆ",
    "Routed to reviewer — do not consume yet": "ಪರಿಶೀಲಕರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ — ಇನ್ನೂ ಬಳಸಬೇಡಿ",
    "FAILED": "ವಿಫಲ",
    "Processing error — see exceptions": "ಸಂಸ್ಕರಣಾ ದೋಷ — ಗುರುತಿಸಿದ ಸಾಲುಗಳನ್ನು ನೋಡಿ",
    "Account": "ಖಾತೆ",
    "Account no": "ಖಾತೆ ಸಂಖ್ಯೆ",
    "Type / currency": "ಪ್ರಕಾರ / ಕರೆನ್ಸಿ",
    "Statement period": "ಸ್ಟೇಟ್‌ಮೆಂಟ್ ಅವಧಿ",
    "Opening balance": "ಆರಂಭಿಕ ಶಿಲ್ಕು",
    "Rows extracted": "ಹೊರತೆಗೆದ ಸಾಲುಗಳು",
    "AI-repaired": "AI ಸರಿಪಡಿಸಿದವು",
    "· AI-repaired": "· AI ಸರಿಪಡಿಸಿದೆ",
    "Reconciliation — stated by document vs recomputed":
        "ಹೊಂದಾಣಿಕೆ — ದಾಖಲೆಯಲ್ಲಿ ನಮೂದಿಸಿದ್ದು ಮತ್ತು ಮರುಲೆಕ್ಕ ಹಾಕಿದ್ದು",
    "Stated": "ನಮೂದಿಸಿದ್ದು",
    "Recomputed": "ಮರುಲೆಕ್ಕ",
    "Debits": "ಡೆಬಿಟ್‌ಗಳು",
    "Credits": "ಕ್ರೆಡಿಟ್‌ಗಳು",
    "Closing balance": "ಅಂತಿಮ ಶಿಲ್ಕು",
    "✓ match": "✓ ಹೊಂದುತ್ತದೆ",
    "✗ mismatch": "✗ ಹೊಂದುವುದಿಲ್ಲ",
    "Totals line not present in document": "ದಾಖಲೆಯಲ್ಲಿ ಒಟ್ಟು ಮೊತ್ತದ ಸಾಲು ಇಲ್ಲ",
    "Flagged rows": "ಗುರುತಿಸಿದ ಸಾಲುಗಳು",
    "Row": "ಸಾಲು",
    "Reason": "ಕಾರಣ",
    "Raw text": "ಮೂಲ ಪಠ್ಯ",
    "Transactions": "ವಹಿವಾಟುಗಳು",
    "Date": "ದಿನಾಂಕ",
    "Txn ID": "ವಹಿವಾಟು ID",
    "Channel": "ಚಾನೆಲ್",
    "Narration": "ವಿವರಣೆ",
    "Debit": "ಡೆಬಿಟ್",
    "Credit": "ಕ್ರೆಡಿಟ್",
    "Balance": "ಶಿಲ್ಕು",
    "Output SHA-256:": "ಔಟ್‌ಪುಟ್ SHA-256:",
    "sealed at write time": "ಬರೆಯುವ ಸಮಯದಲ್ಲಿ ಮುದ್ರೆಯೊತ್ತಲಾಗುತ್ತದೆ",
    "Ledger reference:": "ಲೆಡ್ಜರ್ ಉಲ್ಲೇಖ:",
    "batch decision ledger, doc_processed entry": "ಬ್ಯಾಚ್ ನಿರ್ಧಾರ ಲೆಡ್ಜರ್, doc_processed ನಮೂದು",
    "verify integrity with {0}.": "ಸಮಗ್ರತೆಯನ್ನು ಪರಿಶೀಲಿಸಲು: {0}.",
    "This report was generated deterministically from the sealed output; regenerate at any time from the JSON.":
        "ಈ ವರದಿಯನ್ನು ಮುದ್ರೆಯೊತ್ತಿದ ಔಟ್‌ಪುಟ್‌ನಿಂದ ನಿರ್ಧಾರಾತ್ಮಕವಾಗಿ ರಚಿಸಲಾಗಿದೆ; JSON ನಿಂದ ಯಾವಾಗ ಬೇಕಾದರೂ ಮರುರಚಿಸಬಹುದು.",
}

# Shown under the header in the Kannada view only — on screen and in print.
_NOTE_KN = ("ಸೂಚನೆ: ಶೀರ್ಷಿಕೆಗಳು ಮತ್ತು ಸ್ಥಿತಿ ಪದಗಳನ್ನು ಕನ್ನಡದಲ್ಲಿ ತೋರಿಸಲಾಗಿದೆ. ಏಜೆಂಟ್‌ಗಳು ಬರೆದ ವಿಶ್ಲೇಷಣೆ, "
            "ದಾಖಲೆಗಳಿಂದ ಉಲ್ಲೇಖಿಸಿದ ಪಠ್ಯ, ಹೆಸರುಗಳು ಮತ್ತು ಅಂಕಿಗಳು ಮೂಲ ಭಾಷೆಯಲ್ಲೇ ಇವೆ. "
            "ಅಧಿಕೃತ ದಾಖಲೆ ಇಂಗ್ಲಿಷ್ ಆವೃತ್ತಿ.")


def _pair(en_html: str, kn_html: str) -> str:
    return (f'<span class="l-en">{en_html}</span>'
            f'<span class="l-kn" lang="kn">{kn_html}</span>')


def has(text) -> bool:
    return str(text) in KN


def kn_text(text, *args) -> str:
    """Plain-text Kannada for `text` (English if there is no entry). For <title> etc."""
    text = "" if text is None else str(text)
    out = KN.get(text, text)
    return out.format(*[KN.get(a, a) if isinstance(a, str) else a for a in args]) if args else out


def L(text, *args) -> str:
    """A label in both languages, HTML-escaped.

    `text` is the English wording and the key into KN. Optional `args` fill
    {0}, {1} … placeholders; a string argument that is itself a KN key (a
    document title, a status word) is translated in the Kannada half.
    Unknown text comes back escaped and English-only, so this is safe to wrap
    around values that are usually — but not always — from a fixed vocabulary
    (verdict codes, statuses, confidence levels).
    """
    text = "" if text is None else str(text)
    en = html.escape(text.format(*args) if args else text)
    if text not in KN:
        return en
    return _pair(en, html.escape(kn_text(text, *args)))


def LH(text, *fragments: str) -> str:
    """Like L, but the placeholders are filled with ready-made HTML fragments
    (e.g. <span class="mono">…</span>) that must not be escaped again."""
    text = str(text)
    en = html.escape(text).format(*fragments)
    if text not in KN:
        return en
    return _pair(en, html.escape(KN[text]).format(*fragments))


# Appended to each report's own <style>. System fonts only — no downloads.
CSS = """
/* ── language (English / ಕನ್ನಡ) — see batch_ingest/report_i18n.py ── */
.l-kn,.kn-note{display:none}
html[lang="kn"] .l-en{display:none}
html[lang="kn"] .l-kn{display:inline}
.l-kn{font-family:"Noto Sans Kannada","Nirmala UI","Tunga","Kannada Sangam MN","Kannada MN",sans-serif}
html[lang="kn"] .kn-note{display:block;font-size:12px;color:var(--muted);background:var(--faint);
  border-left:3px solid var(--rule);padding:8px 12px;margin:-8px 0 6px}
html[lang="kn"] body{font-family:"Noto Sans Kannada","Nirmala UI","Tunga","Kannada Sangam MN",
  "Kannada MN",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;line-height:1.65}
html[lang="kn"] .eyebrow,html[lang="kn"] h2,html[lang="kn"] .stamp,html[lang="kn"] .grid th,
html[lang="kn"] .f b,html[lang="kn"] .figs b,html[lang="kn"] .finding-label{letter-spacing:0}
html[lang="kn"] .stamp{font-size:14px;line-height:1.35}
.figs b span,.figs span.l-en,.figs span.l-kn{font-size:inherit}
.langbar{display:flex;justify-content:flex-end;margin:-18px 0 10px}
.langsw{display:inline-flex;align-items:center;gap:7px;padding:5px 10px;border:1px solid var(--rule);
  border-radius:999px;background:#fff;font:600 12px/1 system-ui,-apple-system,"Segoe UI",sans-serif;
  color:var(--muted);cursor:pointer}
.langsw:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.langsw .trk{width:28px;height:15px;border-radius:999px;background:#C5CEDB;position:relative}
.langsw .trk i{position:absolute;top:2px;left:2px;width:11px;height:11px;border-radius:50%;background:#fff}
.langsw .kn{font-family:"Noto Sans Kannada","Nirmala UI","Tunga","Kannada Sangam MN",sans-serif;font-size:13px}
.langsw[aria-checked="false"] .en,.langsw[aria-checked="true"] .kn{color:var(--ink)}
.langsw[aria-checked="true"] .trk{background:var(--ink)}
.langsw[aria-checked="true"] .trk i{left:15px}
@media print{.langbar{display:none}}
"""

# First thing inside <body>. Hidden in print; the printed language is the one on screen.
SWITCH = ('<div class="langbar"><button class="langsw" id="langsw" type="button" role="switch" '
          'aria-checked="false" aria-label="ಕನ್ನಡ — show this report in Kannada" title="English ⇄ ಕನ್ನಡ">'
          '<span class="en">EN</span><span class="trk"><i></i></span>'
          '<span class="kn" lang="kn">ಕನ್ನಡ</span></button></div>')

# Directly after </header>.
NOTE = f'<p class="kn-note" lang="kn">{html.escape(_NOTE_KN)}</p>'

# Last thing inside <body>.
SCRIPT = """<script>
(function(){var K='prefectos_lang',d=document.documentElement,b=document.getElementById('langsw'),
 te=document.title,tk=d.getAttribute('data-title-kn')||te;
 function set(l,keep){l=(l==='kn')?'kn':'en';d.lang=l;document.title=(l==='kn')?tk:te;
  if(b)b.setAttribute('aria-checked',String(l==='kn'));
  if(keep){try{localStorage.setItem(K,l)}catch(e){}}}
 if(b)b.onclick=function(){set(d.lang==='kn'?'en':'kn',true)};
 var s='en';try{s=new URLSearchParams(location.search).get('lang')||localStorage.getItem(K)||'en'}catch(e){}
 set(s,false)})();
</script>"""


def title_attr(kn_title: str) -> str:
    """Attribute for the <html> tag carrying the Kannada <title> text."""
    return f' data-title-kn="{html.escape(kn_title)}"'
