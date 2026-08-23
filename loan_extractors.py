"""
loan_extractors.py — the zero-token fast path for loan documents.

Deterministic parse + arithmetic validation for the four DFBK loan document
layouts. A document that parses and reconciles never touches an LLM; only the
rows that fail validation are escalated, mirroring batch_ingest/extractor.py.

    ExtractionResult.status == "clean"      -> facts are trustworthy, 0 tokens
    ExtractionResult.status == "exception"  -> route ONLY the failing rows
    ExtractionResult.status == "unreadable" -> route the whole document

WHY CHARS AND NOT extract_text():
    In these statements the Credit and Balance columns physically overlap, so
    pdfplumber's x-sorted text layer interleaves their glyphs —
    "55,294.11" + "6,756,646.17" comes out as "55,269,745.161,646.17".
    Reading page.chars in content-stream order and splitting on x-discontinuity
    recovers both numbers exactly. Any pipeline that feeds extract_text() to a
    model is handing it corrupted figures on the fields that decide the case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

TOLERANCE = 0.02          # rupees; covers per-row rounding in the source docs
RATE_TOLERANCE = 1.00     # EMI recomputation vs printed EMI

MONEY = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _is_money(s: str) -> bool:
    return bool(MONEY.match(s))


# ─────────────────────────────────────────────────────────────────────────────
# Layout reader — rows of cells, immune to overlapping columns
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Cell:
    text: str
    x0: float
    x1: float


def page_rows(page) -> list[list[Cell]]:
    """Group chars into visual rows, then into cells in CONTENT-STREAM order.

    A new cell starts when x jumps backwards (a column drawn over a previous
    one) or a horizontal gap opens up. Stream order is what keeps overlapping
    columns apart — never re-sort by x.
    """
    buckets: dict[int, list] = {}
    for ch in page.chars:
        buckets.setdefault(round(ch["top"]), []).append(ch)

    rows: list[list[Cell]] = []
    for top in sorted(buckets):
        cells: list[Cell] = []
        current: list = []
        prev_x1: float | None = None
        for ch in buckets[top]:
            gap = None if prev_x1 is None else ch["x0"] - prev_x1
            if current and (gap is None or gap > 2.0 or gap < -0.5):
                cells.append(_mk_cell(current))
                current = []
            current.append(ch)
            prev_x1 = ch["x1"]
        if current:
            cells.append(_mk_cell(current))
        rows.append([c for c in cells if c.text.strip()])
    return rows


def _mk_cell(chars: list) -> Cell:
    return Cell(text="".join(c["text"] for c in chars).strip(),
                x0=chars[0]["x0"], x1=chars[-1]["x1"])


def read_pdf(path: Path) -> tuple[list[list[Cell]], str]:
    """Return (rows, flat_text). Raises on an unopenable file."""
    import pdfplumber
    rows: list[list[Cell]] = []
    text_parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            rows.extend(page_rows(page))
            text_parts.append(page.extract_text() or "")
    return rows, "\n".join(text_parts)


# ─────────────────────────────────────────────────────────────────────────────
# Result model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    document: str
    doc_type: str = "unknown"       # sanction_letter | salary_slip | emi_schedule
                                    # | loan_statement | unknown
    status: str = "clean"           # clean | exception | unreadable
    fields: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)   # deterministic verdicts
    exceptions: list[dict] = field(default_factory=list)  # row-scoped failures
    rows: int = 0
    elapsed_ms: float = 0.0

    def add_check(self, name: str, ok: bool, stated=None, recomputed=None,
                  detail: str = "") -> None:
        self.checks.append({"check": name, "ok": ok, "stated": stated,
                            "recomputed": recomputed, "detail": detail})

    def fail(self, kind: str, **payload) -> None:
        self.status = "exception"
        self.exceptions.append({"reason": kind, **payload})

    def public(self) -> dict:
        return {"document": self.document, "doc_type": self.doc_type,
                "status": self.status, "fields": self.fields,
                "checks": self.checks, "exceptions": self.exceptions,
                "rows": self.rows, "elapsed_ms": round(self.elapsed_ms, 1)}


# ─────────────────────────────────────────────────────────────────────────────
# Document-type detection
# ─────────────────────────────────────────────────────────────────────────────

TYPE_MARKERS = [
    ("sanction_letter", "SANCTION LETTER"),
    ("emi_schedule",    "EMI REPAYMENT SCHEDULE"),
    ("loan_statement",  "LOAN ACCOUNT STATEMENT"),
    ("salary_slip",     "SALARY SLIP"),
]


def detect_type(flat_text: str) -> str:
    upper = flat_text.upper()
    for name, marker in TYPE_MARKERS:
        if marker in upper:
            return name
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Per-layout parsers
# ─────────────────────────────────────────────────────────────────────────────

def _labelled(rows: list[list[Cell]], label: str) -> str | None:
    """Value of a `Label   Value` row, matched on the row's leading text."""
    for cells in rows:
        joined = " ".join(c.text for c in cells)
        if joined.upper().startswith(label.upper()):
            rest = joined[len(label):].strip()
            if rest:
                return rest
    return None


def parse_sanction_letter(res: ExtractionResult, rows, text) -> None:
    f = res.fields
    for key, label in (("loan_id", "Loan Account No"), ("product", "Product"),
                       ("first_emi", "First EMI Date")):
        val = _labelled(rows, label)
        if val:
            f[key] = val
    for key, label in (("principal", "Sanctioned Amount (Rs)"),
                       ("emi", "EMI (Rs)"), ("fee", "Processing Fee (Rs)")):
        val = _labelled(rows, label)
        if val and _is_money(val):
            f[key] = _num(val)
    m = re.search(r"Interest Rate\s+([\d.]+)%", text)
    if m:
        f["rate"] = float(m.group(1))
    m = re.search(r"Tenure\s+(\d+)\s+months", text)
    if m:
        f["months"] = int(m.group(1))
    m = re.search(r"To:\s*([^,\n]+)", text)
    if m:
        f["borrower"] = m.group(1).strip()

    missing = [k for k in ("principal", "emi", "rate", "months") if k not in f]
    if missing:
        res.fail("sanction_fields_not_found", missing=missing)
        return

    # The EMI must follow from principal, rate and tenure — pure arithmetic.
    r = f["rate"] / 1200.0
    n = f["months"]
    expected = f["principal"] * r * (1 + r) ** n / ((1 + r) ** n - 1)
    ok = abs(expected - f["emi"]) <= RATE_TOLERANCE
    res.add_check("emi_matches_amortisation", ok, f["emi"], round(expected, 2),
                  f"P={f['principal']:,.2f} r={f['rate']}% n={n}")
    if not ok:
        res.fail("emi_mismatch", stated=f["emi"], recomputed=round(expected, 2))


def parse_salary_slip(res: ExtractionResult, rows, text) -> None:
    f = res.fields
    for key, label in (("employee", "Employee"), ("employee_id", "Employee ID"),
                       ("designation", "Designation")):
        val = _labelled(rows, label)
        if val:
            f[key] = val
    for key, label in (("basic", "Basic"), ("hra", "HRA"),
                       ("special_allowance", "Special Allowance"),
                       ("gross", "Gross Earnings"), ("pf", "Provident Fund"),
                       ("tax", "Income Tax (TDS)"),
                       ("deductions", "Total Deductions"), ("net_pay", "NET PAY")):
        val = _labelled(rows, label)
        if val and _is_money(val):
            f[key] = _num(val)
    m = re.search(r"SALARY SLIP\s*[^\w]?\s*(\w+\s+\d{4})", text.upper())
    if m:
        f["period"] = m.group(1).title()

    if "gross" not in f or "net_pay" not in f:
        res.fail("salary_fields_not_found",
                 missing=[k for k in ("gross", "net_pay") if k not in f])
        return

    parts = sum(f.get(k, 0.0) for k in ("basic", "hra", "special_allowance"))
    ok = abs(parts - f["gross"]) <= TOLERANCE
    res.add_check("gross_equals_components", ok, f["gross"], round(parts, 2))
    if not ok:
        res.fail("gross_mismatch", stated=f["gross"], recomputed=round(parts, 2))

    deduct = sum(f.get(k, 0.0) for k in ("pf", "tax"))
    if "deductions" in f:
        ok = abs(deduct - f["deductions"]) <= TOLERANCE
        res.add_check("deductions_sum", ok, f["deductions"], round(deduct, 2))
        if not ok:
            res.fail("deductions_mismatch", stated=f["deductions"],
                     recomputed=round(deduct, 2))

    expected_net = f["gross"] - f.get("deductions", deduct)
    ok = abs(expected_net - f["net_pay"]) <= TOLERANCE
    res.add_check("net_equals_gross_minus_deductions", ok, f["net_pay"],
                  round(expected_net, 2))
    if not ok:
        res.fail("net_pay_mismatch", stated=f["net_pay"],
                 recomputed=round(expected_net, 2))


def parse_emi_schedule(res: ExtractionResult, rows, text) -> None:
    f = res.fields
    m = re.search(r"A/c:\s*(\S+)", text)
    if m:
        f["loan_id"] = m.group(1)
    m = re.search(r"Borrower:\s*(.+?)\s+Principal", text)
    if m:
        f["borrower"] = m.group(1).strip()
    m = re.search(r"Principal Rs\s+([\d,]+\.\d{2})", text)
    if m:
        f["principal"] = _num(m.group(1))
    m = re.search(r"Rate\s+([\d.]+)%", text)
    if m:
        f["rate"] = float(m.group(1))
    m = re.search(r"EMI Rs\s+([\d,]+\.\d{2})", text)
    if m:
        f["emi"] = _num(m.group(1))

    schedule: list[dict] = []
    for cells in rows:
        vals = [c.text for c in cells]
        if len(vals) < 6 or not vals[0].isdigit() or not DATE.match(vals[1]):
            continue
        money = [v for v in vals[2:] if _is_money(v)]
        if len(money) < 4:
            res.fail("schedule_row_unparsed", row=vals[0], raw=" ".join(vals))
            continue
        emi, interest, principal, balance = (_num(x) for x in money[:4])
        schedule.append({"no": int(vals[0]), "due": vals[1], "emi": emi,
                         "interest": interest, "principal": principal,
                         "balance": balance})
    res.rows = len(schedule)
    f["schedule_rows"] = len(schedule)
    if not schedule:
        res.status = "unreadable"
        res.fail("no_schedule_rows")
        return

    # Row arithmetic: interest = balance x rate/12, principal = EMI - interest,
    # and the balance must chain from the previous row.
    rate_m = f.get("rate", 0) / 1200.0
    prev = f.get("principal")
    for row in schedule:
        if prev is not None and rate_m:
            exp_int = round(prev * rate_m, 2)
            if abs(exp_int - row["interest"]) > 1.0:
                res.fail("interest_mismatch", row=row["no"],
                         stated=row["interest"], recomputed=exp_int)
            exp_prin = round(row["emi"] - row["interest"], 2)
            if abs(exp_prin - row["principal"]) > TOLERANCE:
                res.fail("principal_split_mismatch", row=row["no"],
                         stated=row["principal"], recomputed=exp_prin)
            exp_bal = round(prev - row["principal"], 2)
            if abs(exp_bal - row["balance"]) > TOLERANCE:
                res.fail("balance_chain_break", row=row["no"],
                         stated=row["balance"], recomputed=exp_bal)
        prev = row["balance"]

    total_int = round(sum(r["interest"] for r in schedule), 2)
    total_prin = round(sum(r["principal"] for r in schedule), 2)
    closing = schedule[-1]["balance"]
    f["totals_recomputed"] = {"interest": total_int, "principal": total_prin,
                              "closing": closing}

    m = re.search(r"Totals[^:]*:\s*Interest\s+([\d,]+\.\d{2})\s*\|\s*"
                  r"Principal\s+([\d,]+\.\d{2})\s*\|\s*Closing Balance\s+"
                  r"([\d,]+\.\d{2})", text)
    if m:
        stated = {"interest": _num(m.group(1)), "principal": _num(m.group(2)),
                  "closing": _num(m.group(3))}
        f["totals_stated"] = stated
        for key, value in stated.items():
            got = f["totals_recomputed"][key]
            ok = abs(got - value) <= 0.05
            res.add_check(f"schedule_total_{key}", ok, value, got)
            if not ok:
                res.fail(f"schedule_total_{key}_mismatch", stated=value,
                         recomputed=got)


def parse_loan_statement(res: ExtractionResult, rows, text) -> None:
    f = res.fields
    m = re.search(r"A/c:\s*(\S+)", text)
    if m:
        f["loan_id"] = m.group(1)
    m = re.search(r"Borrower\s+(.+?)\s+[^\w]?\s*Product", text)
    if m:
        f["borrower"] = m.group(1).strip()
    m = re.search(r"Statement Period\s+(\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", text)
    if m:
        f["period"] = [m.group(1), m.group(2)]
    m = re.search(r"Opening Balance\s+([\d,]+\.\d{2})", text)
    if m:
        f["opening_balance"] = _num(m.group(1))

    # Column x-anchors from the header row, used to tell Debit from Credit when
    # a row carries only one of them.
    anchors = {}
    for cells in rows:
        labels = [c.text for c in cells]
        if "Debit" in labels and "Credit" in labels and "Balance" in labels:
            for c in cells:
                if c.text in ("Debit", "Credit", "Balance"):
                    anchors[c.text] = c.x0
            break

    txns: list[dict] = []
    for cells in rows:
        vals = [c.text for c in cells]
        if not vals or not DATE.match(vals[0]):
            continue
        money_cells = [c for c in cells if _is_money(c.text)]
        if len(money_cells) < 2:
            res.fail("amounts_not_found", txn=vals[1] if len(vals) > 1 else "?",
                     raw=" ".join(vals))
            continue
        balance = _num(money_cells[-1].text)
        debit = credit = 0.0
        for c in money_cells[:-1]:
            # Nearest column anchor wins; overlapping columns keep their x0.
            if anchors and abs(c.x0 - anchors.get("Credit", 1e9)) < \
                    abs(c.x0 - anchors.get("Debit", 1e9)):
                credit = _num(c.text)
            else:
                debit = _num(c.text)
        txns.append({"date": vals[0], "txn_id": vals[1] if len(vals) > 1 else "",
                     "debit": debit, "credit": credit, "balance": balance})

    res.rows = len(txns)
    f["transactions"] = len(txns)
    if not txns:
        res.status = "unreadable"
        res.fail("no_transactions")
        return

    # Loan account: a debit raises the outstanding, a credit reduces it.
    prev = f.get("opening_balance")
    for t in txns:
        if prev is not None:
            expected = round(prev + t["debit"] - t["credit"], 2)
            if abs(expected - t["balance"]) > TOLERANCE:
                res.fail("balance_chain_break", txn=t["txn_id"],
                         stated=t["balance"], recomputed=expected,
                         date=t["date"])
        prev = t["balance"]

    totals = {"debits": round(sum(t["debit"] for t in txns), 2),
              "credits": round(sum(t["credit"] for t in txns), 2),
              "closing": txns[-1]["balance"]}
    f["totals_recomputed"] = totals

    m = re.search(r"Totals:\s*Debits\s+([\d,]+\.\d{2})\s*\|\s*Credits\s+"
                  r"([\d,]+\.\d{2})\s*\|\s*Closing Balance\s+([\d,]+\.\d{2})", text)
    if m:
        stated = {"debits": _num(m.group(1)), "credits": _num(m.group(2)),
                  "closing": _num(m.group(3))}
        f["totals_stated"] = stated
        for key, value in stated.items():
            got = totals[key]
            ok = abs(got - value) <= 0.05
            res.add_check(f"statement_total_{key}", ok, value, got)
            if not ok:
                res.fail(f"statement_total_{key}_mismatch", stated=value,
                         recomputed=got)


PARSERS = {
    "sanction_letter": parse_sanction_letter,
    "salary_slip":     parse_salary_slip,
    "emi_schedule":    parse_emi_schedule,
    "loan_statement":  parse_loan_statement,
}


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def group_by_applicant(results: list[ExtractionResult]) -> dict[str, list[ExtractionResult]]:
    """Split a folder into one bundle per applicant.

    A folder routinely holds several applicants' files. Checking them as one
    pile silently compares one person's EMI against another's payslip, so the
    loan account number (falling back to the borrower name) is the key.
    """
    groups: dict[str, list[ExtractionResult]] = {}
    for r in results:
        key = (r.fields.get("loan_id")
               or r.fields.get("borrower")
               or r.fields.get("employee")
               or "unidentified")
        groups.setdefault(str(key), []).append(r)

    # Salary slips carry no loan id — attach them to the applicant whose name
    # they match, rather than leaving them in their own bundle.
    named = {k: {str(r.fields.get("borrower") or "") for r in v} for k, v in groups.items()}
    for key in list(groups):
        if key == "unidentified" or any(r.fields.get("loan_id") for r in groups[key]):
            continue
        for other, names in named.items():
            if other != key and key in names:
                groups[other].extend(groups.pop(key))
                break
    return groups


def cross_document_checks(results: list[ExtractionResult]) -> list[dict]:
    """Criteria that span documents — computed in code, not inferred.

    Each verdict is met / not_met / unverified with the figures behind it, so a
    reviewer can re-derive it by hand. 'unverified' means the evidence is
    absent; it never silently becomes 'met'. When the folder holds several
    applicants, every criterion is evaluated per applicant and labelled.
    """
    groups = group_by_applicant(results)
    if len(groups) > 1:
        out: list[dict] = []
        for key, bundle in sorted(groups.items()):
            who = next((r.fields.get("borrower") or r.fields.get("employee")
                        for r in bundle if r.fields.get("borrower")
                        or r.fields.get("employee")), key)
            for check in _checks_for_one_applicant(bundle):
                check["applicant"] = f"{who} ({key})"
                check["criterion"] = f"[{who}] {check['criterion']}"
                out.append(check)
        return out
    return _checks_for_one_applicant(results)


def _checks_for_one_applicant(results: list[ExtractionResult]) -> list[dict]:
    by_type: dict[str, ExtractionResult] = {}
    for r in results:
        by_type.setdefault(r.doc_type, r)

    san = by_type.get("sanction_letter")
    slip = by_type.get("salary_slip")
    sched = by_type.get("emi_schedule")
    stmt = by_type.get("loan_statement")
    out: list[dict] = []

    def verdict(criterion: str, status: str, evidence: str) -> None:
        out.append({"criterion": criterion, "status": status,
                    "evidence": evidence, "source": "deterministic"})

    # 1. FOIR — the EMI against take-home pay.
    emi = (san.fields.get("emi") if san else None) or \
          (sched.fields.get("emi") if sched else None)
    net = slip.fields.get("net_pay") if slip else None
    if emi and net:
        foir = emi / net * 100
        verdict("FOIR (EMI to net income) at or below 50%",
                "met" if foir <= 50 else "not_met",
                f"EMI {emi:,.2f} / net pay {net:,.2f} = {foir:.2f}%")
    else:
        verdict("FOIR (EMI to net income) at or below 50%", "unverified",
                "sanction EMI or salary net pay not available")

    # 2. The same EMI must appear in every document that states one.
    stated = {"sanction letter": san.fields.get("emi") if san else None,
              "EMI schedule": sched.fields.get("emi") if sched else None}
    present = {k: v for k, v in stated.items() if v}
    if len(present) >= 2:
        values = set(round(v, 2) for v in present.values())
        verdict("EMI consistent across documents",
                "met" if len(values) == 1 else "not_met",
                " vs ".join(f"{k} {v:,.2f}" for k, v in present.items()))
    else:
        verdict("EMI consistent across documents", "unverified",
                "fewer than two documents state an EMI")

    # 3. Borrower identity must agree everywhere it appears.
    names = {r.doc_type: (r.fields.get("borrower") or r.fields.get("employee"))
             for r in results}
    names = {k: v for k, v in names.items() if v}
    if len(names) >= 2:
        distinct = set(names.values())
        verdict("Borrower name consistent across documents",
                "met" if len(distinct) == 1 else "not_met",
                "; ".join(f"{k}: {v}" for k, v in names.items()))
    else:
        verdict("Borrower name consistent across documents", "unverified",
                "fewer than two documents name the borrower")

    # 4. Loan account number must agree.
    ids = {r.doc_type: r.fields.get("loan_id") for r in results
           if r.fields.get("loan_id")}
    if len(ids) >= 2:
        verdict("Loan account number consistent",
                "met" if len(set(ids.values())) == 1 else "not_met",
                "; ".join(f"{k}: {v}" for k, v in ids.items()))
    else:
        verdict("Loan account number consistent", "unverified",
                "fewer than two documents carry the account number")

    # 5-6. Each table document must reconcile against its own stated totals.
    for label, res in (("EMI schedule", sched), ("Loan statement", stmt)):
        if res is None:
            verdict(f"{label} reconciles to its stated totals", "unverified",
                    f"no {label.lower()} in the file")
            continue
        failed = [c for c in res.checks if not c["ok"]]
        breaks = [e for e in res.exceptions if "chain" in e.get("reason", "")]
        if res.status == "clean":
            verdict(f"{label} reconciles to its stated totals", "met",
                    f"{res.rows} rows recomputed; every total matches")
        else:
            detail = "; ".join(
                f"row {e.get('row') or e.get('txn')}: stated {e.get('stated')} "
                f"vs recomputed {e.get('recomputed')}" for e in (failed or breaks)[:3])
            verdict(f"{label} reconciles to its stated totals", "not_met",
                    detail or f"{len(res.exceptions)} validation failures")

    # 7. Salary slip internal arithmetic.
    if slip is None:
        verdict("Salary slip arithmetic is internally consistent", "unverified",
                "no salary slip in the file")
    else:
        verdict("Salary slip arithmetic is internally consistent",
                "met" if slip.status == "clean" else "not_met",
                f"gross {slip.fields.get('gross', 0):,.2f}, "
                f"net {slip.fields.get('net_pay', 0):,.2f}")
    return out


def fact_sheet(results: list[ExtractionResult],
               include_cross_checks: bool = True) -> dict:
    """Compact, model-ready summary of everything code already established.

    `include_cross_checks` is loan-specific (FOIR, LTV, EMI consistency); an
    account or KYC set would only collect a wall of 'unverified' noise from it.
    """
    groups = group_by_applicant(results)
    return {
        "applicants_detected": [
            {"key": key,
             "name": next((r.fields.get("borrower") or r.fields.get("employee")
                           for r in bundle if r.fields.get("borrower")
                           or r.fields.get("employee")), None),
             "documents": [r.document for r in bundle]}
            for key, bundle in sorted(groups.items())
        ],
        "documents": [
            {"document": r.document, "type": r.doc_type, "status": r.status,
             "rows": r.rows, "fields": r.fields}
            for r in results
        ],
        "criteria_computed_in_code": (cross_document_checks(results)
                                      if include_cross_checks else []),
        "exceptions": [
            {"document": r.document, "type": r.doc_type,
             "failures": r.exceptions}
            for r in results if r.status != "clean"
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# CSV account statements — the zero-token path for exported statements
#
# A CSV is already structured, so nothing here needs a model. Columns are
# matched by synonym because every bank exports different headers, and the
# debit/credit sign convention is inferred from the data rather than assumed:
# both hypotheses are tested against the balance chain and the one that
# reconciles wins. If neither does, the rows go to the model as exceptions.
# ─────────────────────────────────────────────────────────────────────────────

COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date":        ("date", "txn date", "transaction date", "value date",
                    "posting date", "tran date"),
    "description": ("description", "narration", "particulars", "details",
                    "remarks", "transaction remarks"),
    "debit":       ("debit", "withdrawal", "withdrawal amt", "withdrawal amount",
                    "dr", "debit amount", "paid out"),
    "credit":      ("credit", "deposit", "deposit amt", "deposit amount",
                    "cr", "credit amount", "paid in"),
    "balance":     ("balance", "closing balance", "running balance",
                    "balance amt", "available balance"),
    "amount":      ("amount", "txn amount", "transaction amount"),
    "reference":   ("cheque no", "chq no", "cheque number", "ref no",
                    "reference", "instrument no", "chq/ref no"),
}

RETURN_MARKERS = ("return", "returned", "dishonour", "dishonor", "bounce",
                  "insufficient", "unpaid", "rejected", "inward chq rtn")


def _canon(header: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (header or "").strip().lower()).strip()


def _map_columns(headers: list[str]) -> dict[str, int]:
    """Column name → index, matched on synonyms, longest match first."""
    mapping: dict[str, int] = {}
    canon = [_canon(h) for h in headers]
    for field, names in COLUMN_SYNONYMS.items():
        # Canonicalise the synonyms too — "chq/ref no" must match a header that
        # canonicalises to "chq ref no".
        for name in sorted((_canon(n) for n in names), key=len, reverse=True):
            for idx, header in enumerate(canon):
                if idx in mapping.values() and field != "amount":
                    continue
                if header == name or header.replace(" ", "") == name.replace(" ", ""):
                    mapping[field] = idx
                    break
            if field in mapping:
                break
    return mapping


def _money_or_none(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    s = s.replace("(", "-").replace(")", "")
    if not s or s in ("-", "--"):
        return None
    m = re.fullmatch(r"-?\d+(?:\.\d+)?", s)
    return float(s) if m else None


def parse_csv_statement(res: ExtractionResult, path: Path) -> None:
    import csv as _csv

    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    if not raw.strip():
        res.status = "unreadable"
        res.fail("empty_file")
        return
    try:
        dialect = _csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except _csv.Error:
        dialect = _csv.excel
    rows = [r for r in _csv.reader(raw.splitlines(), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        res.status = "unreadable"
        res.fail("no_data_rows")
        return

    # The header is the first row that maps to at least a date and a balance
    # or an amount — statements often carry preamble lines above it.
    header_idx, cols = None, {}
    for i, row in enumerate(rows[:15]):
        candidate = _map_columns(row)
        if "date" in candidate and ("balance" in candidate or "debit" in candidate
                                    or "credit" in candidate or "amount" in candidate):
            header_idx, cols = i, candidate
            break
    if header_idx is None:
        res.status = "unreadable"
        res.fail("no_recognisable_header",
                 headers=rows[0][:12],
                 detail="no date + amount/balance columns found")
        return

    res.fields["columns_matched"] = {k: rows[header_idx][v] for k, v in cols.items()}

    txns: list[dict] = []
    for line_no, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        def cell(field: str) -> str:
            idx = cols.get(field)
            return row[idx] if idx is not None and idx < len(row) else ""

        date = cell("date").strip()
        if not date:
            continue
        debit = _money_or_none(cell("debit"))
        credit = _money_or_none(cell("credit"))
        amount = _money_or_none(cell("amount"))
        balance = _money_or_none(cell("balance"))
        if debit is None and credit is None and amount is not None:
            # Single signed amount column: negative is a debit.
            debit, credit = (abs(amount), None) if amount < 0 else (None, amount)
        if debit is None and credit is None:
            res.fail("amounts_not_found", row=line_no, raw=" | ".join(row)[:200])
            continue
        txns.append({"row": line_no, "date": date,
                     "description": cell("description").strip(),
                     "reference": cell("reference").strip(),
                     "debit": debit or 0.0, "credit": credit or 0.0,
                     "balance": balance})

    res.rows = len(txns)
    if not txns:
        res.status = "unreadable"
        res.fail("no_transactions_parsed")
        return

    total_debits = round(sum(t["debit"] for t in txns), 2)
    total_credits = round(sum(t["credit"] for t in txns), 2)

    # Sign convention: a deposit account credits up, a loan account debits up.
    # Test both against the chain and keep whichever reconciles.
    balances = [t["balance"] for t in txns if t["balance"] is not None]
    convention, breaks = None, []
    if len(balances) >= 2:
        for name, sign in (("deposit", -1), ("loan", +1)):
            candidate_breaks = []
            prev = None
            for t in txns:
                if t["balance"] is None:
                    continue
                if prev is not None:
                    expected = round(prev + sign * t["debit"] - sign * t["credit"], 2)
                    if abs(expected - t["balance"]) > TOLERANCE:
                        candidate_breaks.append(
                            {"reason": "balance_chain_break", "row": t["row"],
                             "date": t["date"], "stated": t["balance"],
                             "recomputed": expected})
                prev = t["balance"]
            if convention is None or len(candidate_breaks) < len(breaks):
                convention, breaks = name, candidate_breaks
            if not candidate_breaks:
                break
    res.fields["sign_convention"] = convention
    for b in breaks:
        res.fail(**b)

    # Average balance: mean of daily closing balances, carrying a day forward
    # when it has no transaction. Falls back to the mean of stated balances
    # when the dates cannot be parsed.
    daily: dict[str, float] = {}
    for t in txns:
        if t["balance"] is not None:
            daily[t["date"]] = t["balance"]
    average_balance = None
    parsed_days = _to_dates(list(daily))
    if parsed_days and len(parsed_days) == len(daily):
        ordered = sorted(parsed_days.items(), key=lambda kv: kv[1])
        first, last = ordered[0][1], ordered[-1][1]
        span = (last - first).days + 1
        if 0 < span <= 3660:
            carried, total, cursor = None, 0.0, first
            by_day = {parsed_days[k]: v for k, v in daily.items()}
            from datetime import timedelta
            while cursor <= last:
                if cursor in by_day:
                    carried = by_day[cursor]
                if carried is not None:
                    total += carried
                cursor += timedelta(days=1)
            average_balance = round(total / span, 2)
            res.fields["average_balance_basis"] = (
                f"mean of daily closing balances across {span} days "
                f"({first.isoformat()} to {last.isoformat()}), days without a "
                f"transaction carried forward")
    if average_balance is None and balances:
        average_balance = round(sum(balances) / len(balances), 2)
        res.fields["average_balance_basis"] = (
            f"mean of the {len(balances)} stated closing balances "
            f"(dates could not be parsed, so no daily carry-forward)")

    returns = [
        {"row": t["row"], "date": t["date"], "amount": t["debit"] or t["credit"],
         "reference": t["reference"],
         "reason": t["description"]}
        for t in txns
        if any(m in t["description"].lower() for m in RETURN_MARKERS)
    ]

    res.fields.update({
        "transactions": len(txns),
        "period": [txns[0]["date"], txns[-1]["date"]],
        "opening_balance_implied": (
            round(txns[0]["balance"] - (txns[0]["credit"] - txns[0]["debit"]), 2)
            if txns[0]["balance"] is not None else None),
        "closing_balance": txns[-1]["balance"],
        "total_debits": total_debits,
        "debit_count": sum(1 for t in txns if t["debit"]),
        "total_credits": total_credits,
        "credit_count": sum(1 for t in txns if t["credit"]),
        "average_balance": average_balance,
        "cheques_returned": len(returns),
        "returns": returns,
    })
    res.add_check("balance_chain_reconciles", not breaks,
                  detail=f"{len(txns)} rows, {convention or 'unknown'} convention")


def _to_dates(values: list[str]) -> dict[str, "date"]:
    """Parse statement dates in the formats banks actually export."""
    from datetime import datetime as _dt
    formats = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%Y",
               "%d %b %Y", "%d-%b-%y", "%Y/%m/%d", "%d.%m.%Y")
    out: dict[str, Any] = {}
    for value in values:
        for fmt in formats:
            try:
                out[value] = _dt.strptime(value.strip(), fmt).date()
                break
            except ValueError:
                continue
    return out


def extract_document(path: Path) -> ExtractionResult:
    """Parse and validate one document. Never raises — failures become status."""
    import time
    t0 = time.perf_counter()
    res = ExtractionResult(document=path.name)

    # CSVs are already structured — parse them directly rather than asking a
    # PDF reader to open them.
    if path.suffix.lower() == ".csv":
        res.doc_type = "csv_statement"
        try:
            parse_csv_statement(res, path)
        except Exception as exc:                                  # noqa: BLE001
            res.status = "exception"
            res.fail("parser_error", error=f"{type(exc).__name__}: {exc}")
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return res

    try:
        rows, text = read_pdf(path)
    except Exception as exc:                                      # noqa: BLE001
        res.status = "unreadable"
        res.fail("could_not_open", error=f"{type(exc).__name__}: {exc}")
        res.elapsed_ms = (time.perf_counter() - t0) * 1000
        return res

    res.doc_type = detect_type(text)
    parser = PARSERS.get(res.doc_type)
    if parser is None:
        # Readable, just not a layout any parser knows — it goes to the model
        # in full. "unreadable" would be both alarming and untrue.
        res.status = "unreadable"
        res.fail("no_parser_for_layout",
                 detail="no deterministic parser matches this layout; "
                        "the document is sent to the model in full")
    else:
        try:
            parser(res, rows, text)
        except Exception as exc:                                  # noqa: BLE001
            res.status = "exception"
            res.fail("parser_error", error=f"{type(exc).__name__}: {exc}")
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    return res
