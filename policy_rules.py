"""
policy_rules.py — apply the bank's numeric thresholds in code, not in the model.

A credit policy is mostly prose, but the parts that decide an application are
arithmetic: an income band selects a FOIR ceiling, a sanctioned amount selects
an LTV ceiling, a bureau score meets a minimum or it doesn't. Handing those to
a language model costs tokens and invites exactly the error we measured — on a
net income of Rs 57,351.95 the model wrote "band appears to be <= 50,000",
which is both wrong and self-contradictory.

So the bands are parsed out of the policy once, the selection and the
comparison happen here, and the model is given the verdict plus the verbatim
clause to cite. Same provenance, fewer tokens, no arithmetic in the model.

Two sources of rules, in order:

  1. `rules.json` in the policy folder — operator-authored and authoritative.
     Write one when the prose is too irregular to parse, or when you want the
     thresholds reviewed and signed off rather than inferred.
  2. Otherwise the prose is parsed (bands, ceilings, minimums) and the result
     is written beside the index as `rules.auto.json` for review.

What is deliberately NOT automated: bands carrying a condition this code cannot
verify ("above Rs 3,00,000 *with a banking relationship of 24 months*") are
parsed, flagged, and left to the model and the human. Code only settles what
code can actually check.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("orchestrator")

RULES_FILENAME = "rules.json"
AUTO_RULES_FILENAME = "rules.auto.json"

_MULTIPLIER = {"lakh": 100_000, "lakhs": 100_000,
               "crore": 10_000_000, "crores": 10_000_000}

# "Rs 50,000", "Rs 1,00,000", "Rs 30 lakh", "1 crore"
_MONEY = re.compile(
    r"(?:Rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|crores?)?", re.IGNORECASE)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CLAUSE = re.compile(r"^\s*(\d+\.\d+)\b")
# The trailing qualifier that makes a band conditional.
_CONDITION = re.compile(r"\bwith\b(?!in)(.+?)(?:\s*[-–—]|$)", re.IGNORECASE)


def _money(raw: str, unit: str | None) -> float:
    value = float(raw.replace(",", ""))
    if unit:
        value *= _MULTIPLIER[unit.lower()]
    return value


def _fmt_inr(value: float) -> str:
    """Indian grouping — 57,351.95 not 57,351.95 the western way at 6+ digits."""
    whole, _, frac = f"{value:.2f}".partition(".")
    neg, whole = (whole[0] == "-"), whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"{'-' if neg else ''}{whole}.{frac}"


# ── parsing bands out of policy prose ────────────────────────────────────────

MIN_BAND_AMOUNT = 1000     # policies band on thousands, never on "5.3" or "two"


def _band_from_line(line: str) -> dict | None:
    """One enumerated band line -> bounds, ceiling, and any condition.

    A band line reads "<range> — <ceiling>%". Everything about the range lives
    before the separator, so the ceiling's own "up to 60%" can't be mistaken
    for an upper bound, and a trailing condition is lifted out before the
    bounds are read.
    """
    pct = _PCT.search(line)
    if not pct:
        return None

    # A leading clause number ("5.3 Vehicle loans:") is not an amount.
    head = _CLAUSE.sub("", line[:pct.start()], count=1)
    # "<range> - <ceiling text>" — keep only the range side.
    range_part = re.split(r"\s+[-–—]\s+|:\s+", head)[0]

    cond = ""
    m = _CONDITION.search(range_part)
    if m and m.group(1).strip():
        cond = m.group(1).strip(" ,.")
        range_part = range_part[:m.start()]

    amounts = [a for a in (_money(m.group(1), m.group(2))
                           for m in _MONEY.finditer(range_part))
               if a >= MIN_BAND_AMOUNT]
    if not amounts:
        return None

    low = re.search(r"\b(above|over|exceeding)\b", range_part, re.IGNORECASE)
    upto = re.search(r"\b(up to|upto|not exceeding|below|under)\b",
                     range_part, re.IGNORECASE)

    if len(amounts) >= 2:                   # "X to Y", "above X and up to Y"
        lo, hi = min(amounts[:2]), max(amounts[:2])
    elif low:                               # "above X"
        lo, hi = amounts[0], float("inf")
    elif upto:                              # "up to X"
        lo, hi = 0.0, amounts[0]
    else:                                   # a bare amount — treat as a ceiling
        lo, hi = 0.0, amounts[0]

    return {"min": lo, "max": hi, "ceiling_pct": float(pct.group(1)),
            "condition": cond, "text": re.sub(r"\s+", " ", line.strip())}


def _section_clause(lines: list[str], idx: int) -> str:
    """The nearest clause number at or above this line (4.2, 5.1 …)."""
    for i in range(idx, -1, -1):
        m = _CLAUSE.match(lines[i])
        if m:
            return m.group(1)
    return ""


def parse_rules_from_text(text: str, source: str) -> dict:
    """Best-effort extraction of the numeric rules from one policy document."""
    lines = text.splitlines()
    rules: dict = {}

    def collect(key: str, keywords: tuple[str, ...]) -> None:
        bands, clause = [], ""
        for i, line in enumerate(lines):
            window = " ".join(lines[max(0, i - 6):i + 1]).lower()
            if not any(k in window for k in keywords):
                continue
            band = _band_from_line(line)
            if not band:
                continue
            band["clause"] = _section_clause(lines, i)
            clause = clause or band["clause"]
            bands.append(band)
        if bands:
            rules[key] = {"source": source, "clause": clause, "bands": bands}

    collect("foir", ("foir", "fixed obligation", "repayment capacity"))
    collect("ltv", ("loan to value", "ltv", "loan-to-value"))

    m = re.search(r"bureau score of\s*(\d{3})\s*or above", text, re.IGNORECASE)
    if m:
        idx = text[:m.start()].count("\n")
        rules["bureau_score"] = {
            "source": source, "clause": _section_clause(lines, idx),
            "minimum": int(m.group(1)),
            "text": re.sub(r"\s+", " ", lines[idx].strip()),
        }
    return rules


def load_rules(policy_path: str | Path, index_dir: str | Path | None = None) -> dict:
    """Operator-authored rules.json if present, else parsed from the prose."""
    p = Path(policy_path).expanduser()
    authored = p / RULES_FILENAME if p.is_dir() else p.parent / RULES_FILENAME
    if authored.exists():
        try:
            rules = json.loads(authored.read_text(encoding="utf-8"))
            rules["_origin"] = f"authored ({authored.name})"
            return rules
        except Exception as exc:                                 # noqa: BLE001
            log.warning("policy ▶ %s is unreadable (%s) — falling back to the prose",
                        authored, exc)

    import loan_processing as _lp
    merged: dict = {}
    supported, _ = _lp.scan_documents(p)
    for f in supported:
        if f.name == RULES_FILENAME:
            continue
        try:
            text, _kind = _lp.extract_text(f)
        except Exception:                                        # noqa: BLE001
            continue
        for key, value in parse_rules_from_text(text or "", f.name).items():
            merged.setdefault(key, value)
    merged["_origin"] = "parsed from the policy prose"

    if index_dir and len(merged) > 1:
        try:
            Path(index_dir).mkdir(parents=True, exist_ok=True)
            (Path(index_dir) / AUTO_RULES_FILENAME).write_text(
                json.dumps(merged, indent=2), encoding="utf-8")
        except OSError:
            pass
    return merged


# ── selection and application ────────────────────────────────────────────────

def select_band(bands: list[dict], value: float) -> tuple[dict | None, list[dict]]:
    """The applicable band for a value, plus any conditional band that could
    also apply if a condition this code cannot check turns out to hold."""
    matching = [b for b in bands if b["min"] <= value <= b["max"]]
    unconditional = [b for b in matching if not b["condition"]]
    conditional = [b for b in matching if b["condition"]]
    if not unconditional:
        return (conditional[0] if conditional else None), []
    # Narrowest wins — "above Rs 1,00,000" should not beat "50,001 to 1,00,000".
    chosen = min(unconditional, key=lambda b: b["max"] - b["min"])
    return chosen, conditional


def _check(criterion: str, status: str, evidence: str, clause: str,
           source: str, quote: str = "") -> dict:
    return {"criterion": criterion, "status": status, "evidence": evidence,
            "source": "policy", "clause": clause, "policy_source": source,
            "clause_text": quote}


def apply_rules(rules: dict, facts: dict) -> list[dict]:
    """Every check the policy's numbers allow code to settle for one applicant.

    facts: {name, net_pay, emi, principal, property_value, bureau_score}
    """
    who = facts.get("name") or ""
    tag = f"[{who}] " if who else ""
    out: list[dict] = []

    # ── FOIR: the band is chosen by income, then the ratio is compared ───────
    foir = rules.get("foir")
    if foir and foir.get("bands"):
        net, emi = facts.get("net_pay"), facts.get("emi")
        if net and emi:
            band, also = select_band(foir["bands"], net)
            ratio = emi / net * 100
            if band:
                ceiling = band["ceiling_pct"]
                status = "met" if ratio <= ceiling else "not_met"
                extra = (f"; a conditional band ({also[0]['condition']}) would "
                         f"allow {also[0]['ceiling_pct']:.0f}%" if also else "")
                out.append(_check(
                    f"{tag}FOIR within the policy ceiling",
                    status,
                    f"EMI {_fmt_inr(emi)} / net {_fmt_inr(net)} = {ratio:.2f}% "
                    f"vs {ceiling:.0f}% ceiling (income selects band "
                    f"{band['text'].split()[0]}){extra}",
                    band.get("clause") or foir.get("clause", ""),
                    foir["source"], band["text"]))
            else:
                out.append(_check(
                    f"{tag}FOIR within the policy ceiling", "unverified",
                    f"No FOIR band in the policy covers a net income of "
                    f"{_fmt_inr(net)}.", foir.get("clause", ""), foir["source"]))
        else:
            missing = "net income" if not net else "EMI"
            out.append(_check(
                f"{tag}FOIR within the policy ceiling", "unverified",
                f"{missing} not available in the documents supplied.",
                foir.get("clause", ""), foir["source"]))

    # ── LTV: the ceiling follows from the sanctioned amount ─────────────────
    ltv = rules.get("ltv")
    if ltv and ltv.get("bands"):
        principal, value = facts.get("principal"), facts.get("property_value")
        if principal:
            band, _ = select_band(ltv["bands"], principal)
            if band and value:
                ratio = principal / value * 100
                status = "met" if ratio <= band["ceiling_pct"] else "not_met"
                out.append(_check(
                    f"{tag}Loan to value within the policy ceiling", status,
                    f"Sanctioned {_fmt_inr(principal)} / property value "
                    f"{_fmt_inr(value)} = {ratio:.2f}% against a "
                    f"{band['ceiling_pct']:.0f}% ceiling for band "
                    f"\"{band['text']}\".",
                    band.get("clause") or ltv.get("clause", ""),
                    ltv["source"], band["text"]))
            elif band:
                out.append(_check(
                    f"{tag}Loan to value within the policy ceiling", "unverified",
                    f"Sanctioned {_fmt_inr(principal)} selects band "
                    f"{band['text'].split()[0]}, ceiling "
                    f"{band['ceiling_pct']:.0f}%; no valuation in the file",
                    band.get("clause") or ltv.get("clause", ""),
                    ltv["source"], band["text"]))

    # ── Bureau score: a flat minimum ────────────────────────────────────────
    bureau = rules.get("bureau_score")
    if bureau:
        score = facts.get("bureau_score")
        minimum = bureau["minimum"]
        if score:
            out.append(_check(
                f"{tag}Bureau score at or above the policy minimum",
                "met" if score >= minimum else "not_met",
                f"Score {score} against a minimum of {minimum}.",
                bureau.get("clause", ""), bureau["source"], bureau.get("text", "")))
        else:
            out.append(_check(
                f"{tag}Bureau score at or above the policy minimum", "unverified",
                f"Requires {minimum}+; no bureau report in the file",
                bureau.get("clause", ""), bureau["source"], bureau.get("text", "")))
    return out


# ── facts out of the extractor's fact sheet ──────────────────────────────────

_FIELD_SOURCES = {
    "net_pay": ("net_pay",),
    "emi": ("emi",),
    "principal": ("principal",),
    "property_value": ("property_value", "assessed_value", "agreement_value"),
    "bureau_score": ("bureau_score", "credit_score", "cibil"),
}


def facts_from_fact_sheet(fact_sheet: dict) -> list[dict]:
    """One facts dict per applicant, from what the extractors already parsed."""
    docs = {d["document"]: (d.get("fields") or {})
            for d in (fact_sheet.get("documents") or [])}
    groups = fact_sheet.get("applicants_detected") or []
    if not groups:
        groups = [{"key": "", "name": None, "documents": list(docs)}]

    out = []
    for g in groups:
        merged: dict = {"name": g.get("name") or g.get("key") or ""}
        for doc in g.get("documents") or []:
            fields = docs.get(doc) or {}
            for target, names in _FIELD_SOURCES.items():
                if merged.get(target) is not None:
                    continue
                for n in names:
                    if isinstance(fields.get(n), (int, float)):
                        merged[target] = float(fields[n])
                        break
            if not merged["name"]:
                merged["name"] = fields.get("borrower") or fields.get("employee") or ""
        out.append(merged)
    return out


def render_context(checks: list[dict]) -> str:
    """The prompt section: the clauses to cite, and the instruction to trust them.

    Deliberately does NOT repeat the checks — they travel in the fact sheet as
    criteria computed in code, like every other deterministic result, and
    sending them twice was costing more tokens than the whole feature saved.
    Each clause is quoted once here, however many checks rely on it.
    """
    if not checks:
        return ""
    settled = [c for c in checks if c["status"] in ("met", "not_met")]

    quotes: dict[str, str] = {}
    for c in checks:
        if c.get("clause_text"):
            key = f"{c['policy_source']} clause {c['clause']}".strip()
            quotes.setdefault(key, c["clause_text"])

    lines = ["", "## Credit policy — thresholds already applied in code", "",
             f"{len(checks)} policy criteria appear in the fact sheet with "
             f"source \"policy\" ({len(settled)} decided, the rest unverified for "
             f"want of a document). The bands were selected from the clauses "
             f"below and compared against the parsed figures by the pipeline. "
             f"Treat them as settled: do not re-select a band, recompute a "
             f"ratio, or restate a ceiling — carry them through and cite the "
             f"clause.", ""]
    if quotes:
        lines += ["Clauses relied on, verbatim:"]
        lines += [f"  {k}: \"{v}\"" for k, v in quotes.items()]
        lines.append("")
    return "\n".join(lines)


def lean(checks: list[dict]) -> list[dict]:
    """Checks without the verbatim clause text — that is quoted once, above."""
    return [{k: v for k, v in c.items() if k != "clause_text"} for c in checks]


def sources_settled(checks: list[dict]) -> tuple[str, ...]:
    """Documents whose rule code actually decided, so retrieval can skip them.

    Only decided checks count. A check left "unverified" for want of a document
    settles nothing, and suppressing that clause would hide from the model the
    very requirement the file fails to evidence.
    """
    return tuple({c["policy_source"] for c in checks
                  if c.get("policy_source") and c["status"] in ("met", "not_met")})
