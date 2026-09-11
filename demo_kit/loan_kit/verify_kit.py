"""Check the kit still produces the findings the demo script promises.

    python demo_kit/loan_kit/verify_kit.py        (needs pdfplumber)

Run it before a client demo, and after any change to `loan_extractors.py`.
It drives the real extractors — the same code path the pipeline uses — and
compares the result against the expectations written down in EXPECTED.md.
Exit code 0 means the demo will say what the runbook says it will.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import loan_extractors as lx          # noqa: E402
import loan_processing as lp          # noqa: E402

BUNDLES = Path(__file__).resolve().parent / "bundles"

FOIR = "FOIR (EMI to net income) at or below 50%"
EMI_CONSISTENT = "EMI consistent across documents"
NAME = "Borrower name consistent across documents"
ACCOUNT = "Loan account number consistent"
SCHEDULE = "EMI schedule reconciles to its stated totals"
STATEMENT = "Loan statement reconciles to its stated totals"
SLIP = "Salary slip arithmetic is internally consistent"

failures: list[str] = []
checks = 0


def expect(label: str, got, want) -> None:
    global checks
    checks += 1
    if got != want:
        failures.append(f"{label}\n      expected {want!r}\n      got      {got!r}")


def parse(folder: str) -> list[lx.ExtractionResult]:
    files = sorted(p for p in (BUNDLES / folder).iterdir() if p.is_file())
    return [lx.extract_document(p) for p in files]


def reasons(results, doc_type: str) -> set[str]:
    return {e["reason"] for r in results if r.doc_type == doc_type
            for e in r.exceptions}


def verdicts(results) -> dict[str, str]:
    return {c["criterion"]: c["status"] for c in lx.cross_document_checks(results)}


def check_clean_loan(folder: str, documents: int, has_statement: bool) -> None:
    """A bundle whose every document reconciles and whose FOIR passes."""
    res = parse(folder)
    expect(f"{folder}: documents parsed", len(res), documents)
    expect(f"{folder}: every document clean",
           sorted({r.status for r in res}), ["clean"])
    expect(f"{folder}: no exceptions", sum(len(r.exceptions) for r in res), 0)
    v = verdicts(res)
    expect(f"{folder}: FOIR passes", v[FOIR], "met")
    expect(f"{folder}: EMI agrees across documents", v[EMI_CONSISTENT], "met")
    expect(f"{folder}: borrower name consistent", v[NAME], "met")
    expect(f"{folder}: loan account number consistent", v[ACCOUNT], "met")
    expect(f"{folder}: schedule reconciles", v[SCHEDULE], "met")
    expect(f"{folder}: statement reconciles", v[STATEMENT],
           "met" if has_statement else "unverified")
    expect(f"{folder}: salary slip arithmetic", v[SLIP], "met")


# ── the positive bundles: every document reconciles, every criterion met ─────
check_clean_loan("home_loan_positive", documents=4, has_statement=True)
check_clean_loan("mortgage_loan_positive", documents=4, has_statement=True)
check_clean_loan("personal_loan_positive", documents=3, has_statement=False)
check_clean_loan("vehicle_loan_positive", documents=3, has_statement=False)

# ── home loan negative: four seeded defects, one per document ────────────────
bad = parse("home_loan_negative")
expect("home_loan_negative: documents parsed", len(bad), 4)
expect("home_loan_negative: sanction letter defect",
       reasons(bad, "sanction_letter"), {"emi_mismatch"})
expect("home_loan_negative: salary slip defect",
       reasons(bad, "salary_slip"), {"net_pay_mismatch"})
expect("home_loan_negative: EMI schedule defect",
       reasons(bad, "emi_schedule"),
       {"balance_chain_break", "interest_mismatch"})
expect("home_loan_negative: loan statement defect",
       reasons(bad, "loan_statement"), {"statement_total_closing_mismatch"})

v = verdicts(bad)
expect("home_loan_negative: FOIR fails", v[FOIR], "not_met")
expect("home_loan_negative: EMI disagrees", v[EMI_CONSISTENT], "not_met")
expect("home_loan_negative: borrower name still consistent", v[NAME], "met")
expect("home_loan_negative: account number still consistent", v[ACCOUNT], "met")
expect("home_loan_negative: schedule does not reconcile", v[SCHEDULE], "not_met")
expect("home_loan_negative: statement does not reconcile", v[STATEMENT], "not_met")
expect("home_loan_negative: salary slip arithmetic fails", v[SLIP], "not_met")

# ── mortgage loan negative: the file does not hang together ──────────────────
# No figure is wrong on its own. The schedule's totals line disagrees with the
# rows above it, and the statement names a different borrower from the rest of
# the file.
mortgage_bad = parse("mortgage_loan_negative")
expect("mortgage_loan_negative: documents parsed", len(mortgage_bad), 4)
expect("mortgage_loan_negative: only the schedule is an exception",
       sorted(r.doc_type for r in mortgage_bad if r.status != "clean"),
       ["emi_schedule"])
expect("mortgage_loan_negative: schedule totals defect",
       reasons(mortgage_bad, "emi_schedule"),
       {"schedule_total_interest_mismatch"})

v = verdicts(mortgage_bad)
expect("mortgage_loan_negative: borrower name disagrees", v[NAME], "not_met")
expect("mortgage_loan_negative: schedule does not reconcile", v[SCHEDULE], "not_met")
expect("mortgage_loan_negative: FOIR still passes", v[FOIR], "met")
expect("mortgage_loan_negative: EMI still agrees", v[EMI_CONSISTENT], "met")
expect("mortgage_loan_negative: account number still consistent", v[ACCOUNT], "met")
expect("mortgage_loan_negative: statement reconciles", v[STATEMENT], "met")
expect("mortgage_loan_negative: salary slip arithmetic", v[SLIP], "met")

# ── vehicle loan negative: the servicing documents do not tie ────────────────
# The sanction terms and the schedule are sound. The payslip's deductions
# column is 2,000 short, and the loan account's running balance jumps once.
vehicle_bad = parse("vehicle_loan_negative")
expect("vehicle_loan_negative: documents parsed", len(vehicle_bad), 4)
expect("vehicle_loan_negative: sanction letter and schedule are clean",
       sorted(r.doc_type for r in vehicle_bad if r.status == "clean"),
       ["emi_schedule", "sanction_letter"])
expect("vehicle_loan_negative: salary slip defect",
       reasons(vehicle_bad, "salary_slip"), {"deductions_mismatch"})
expect("vehicle_loan_negative: statement defect",
       reasons(vehicle_bad, "loan_statement"), {"balance_chain_break"})
expect("vehicle_loan_negative: exactly two rows break the chain",
       sum(1 for r in vehicle_bad if r.doc_type == "loan_statement"
           for e in r.exceptions), 2)

v = verdicts(vehicle_bad)
expect("vehicle_loan_negative: statement does not reconcile", v[STATEMENT], "not_met")
expect("vehicle_loan_negative: salary slip arithmetic fails", v[SLIP], "not_met")
expect("vehicle_loan_negative: FOIR still passes", v[FOIR], "met")
expect("vehicle_loan_negative: EMI still agrees", v[EMI_CONSISTENT], "met")
expect("vehicle_loan_negative: borrower name consistent", v[NAME], "met")
expect("vehicle_loan_negative: account number consistent", v[ACCOUNT], "met")
expect("vehicle_loan_negative: schedule reconciles", v[SCHEDULE], "met")

# ── personal loan negative: arithmetic clean, policy fails ───────────────────
personal = parse("personal_loan_negative")
expect("personal_loan_negative: documents parsed", len(personal), 3)
expect("personal_loan_negative: every document clean",
       sorted({r.status for r in personal}), ["clean"])
expect("personal_loan_negative: no arithmetic exceptions",
       sum(len(r.exceptions) for r in personal), 0)
v = verdicts(personal)
expect("personal_loan_negative: FOIR fails", v[FOIR], "not_met")
expect("personal_loan_negative: nothing else fails",
       sorted(s for c, s in v.items() if c != FOIR),
       ["met", "met", "met", "met", "met", "unverified"])

# ── two applicants in one folder ─────────────────────────────────────────────
mixed = parse("home_loan_two_applicants")
sheet = lx.fact_sheet(mixed)
expect("two_applicants: documents parsed", len(mixed), 8)
expect("two_applicants: applicants detected",
       [a["key"] for a in sheet["applicants_detected"]],
       ["HL-2026-004471", "HL-2026-004902"])
expect("two_applicants: applicants named",
       [a["name"] for a in sheet["applicants_detected"]],
       ["Priya Raghavan", "Arjun Mehta"])
expect("two_applicants: four documents each",
       [len(a["documents"]) for a in sheet["applicants_detected"]], [4, 4])
expect("two_applicants: criteria evaluated per applicant",
       len(sheet["criteria_computed_in_code"]), 14)
expect("two_applicants: only the second applicant fails",
       sorted({c["applicant"] for c in sheet["criteria_computed_in_code"]
               if c["status"] == "not_met"}),
       ["Arjun Mehta (HL-2026-004902)"])

# ── CSV current account — the zero-token path ────────────────────────────────
csv_res = parse("account_statement_csv")
expect("account_statement_csv: one statement", len(csv_res), 1)
stmt = csv_res[0]
f = stmt.fields
expect("account_statement_csv: parsed as a CSV statement",
       stmt.doc_type, "csv_statement")
expect("account_statement_csv: statement is clean", stmt.status, "clean")
expect("account_statement_csv: transactions", f.get("transactions"), 24)
expect("account_statement_csv: sign convention inferred",
       f.get("sign_convention"), "deposit")
expect("account_statement_csv: balance chain reconciles", stmt.exceptions, [])
expect("account_statement_csv: cheques returned", f.get("cheques_returned"), 2)
expect("account_statement_csv: total debits", f.get("total_debits"), 2_180_150.00)
expect("account_statement_csv: total credits", f.get("total_credits"), 2_530_070.00)
expect("account_statement_csv: closing balance",
       f.get("closing_balance"), 1_634_420.00)
expect("account_statement_csv: columns matched by synonym",
       sorted(f.get("columns_matched", {})),
       ["balance", "credit", "date", "debit", "description", "reference"])

# ── sets with no deterministic parser: they must reach the model intact ──────
for folder, count in (("kyc_set", 4), ("general_mixed", 3)):
    supported, skipped = lp.scan_documents(BUNDLES / folder)
    expect(f"{folder}: documents discoverable", len(supported), count)
    expect(f"{folder}: nothing skipped as unsupported", skipped, [])

# ── Application-stage packs (application_docs.py) ───────────────────────────
# Positive / negative per product, written against the processing prompts.
# The engine reconciles the salary slip in code and hands the rest to the
# model; what is checked here is the part that is deterministic: the slip
# parses (and the one seeded tamper is caught), every document classifies to
# its intake template, the set is complete, and no document carries a stray
# extractor type marker that would make the engine mis-parse it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import application_docs as appdocs                        # noqa: E402
from email_validation import DocumentValidator, extract_pdf_text   # noqa: E402

_templates = DocumentValidator.load(REPO / "doc_templates.json")
for pack, (product, _fn) in appdocs.PACK_SPECS.items():
    folder = BUNDLES / pack
    pdfs = sorted(f for f in folder.iterdir() if f.suffix == ".pdf")
    expect(f"{pack}: documents present", len(pdfs) >= 5, True)
    expect(f"{pack}: README present", (folder / "README.txt").exists(), True)
    classified = []
    for f in pdfs:
        c = _templates.classify(f.name, f.read_bytes())
        classified.append(c)
        expect(f"{pack}: {f.name} classifies to an intake template",
               c.doc_type is not None, True)
        text = extract_pdf_text(f.read_bytes())[0].upper()
        for tname, marker in lx.TYPE_MARKERS:
            if not (tname == "salary_slip" and "income_proof" in f.name):
                expect(f"{pack}: {f.name} carries no stray '{marker}' marker",
                       marker in text, False)
    complete, missing = _templates.check_set(product, classified)
    expect(f"{pack}: document set complete for {product}", (complete, missing), (True, []))
    slip = lx.extract_document(next(f for f in pdfs if "income_proof" in f.name))
    expect(f"{pack}: salary slip parsed in code", (slip.doc_type, "net_pay" in slip.fields),
           ("salary_slip", True))
    if pack == "home_loan_application_negative":
        expect(f"{pack}: seeded salary tamper is caught",
               "gross_mismatch" in reasons([slip], "salary_slip"), True)
    else:
        expect(f"{pack}: salary slip reconciles", slip.status, "clean")


# ── Excel twins ──────────────────────────────────────────────────────────────
# bundles_excel/ mirrors bundles/, document for document. Excel has no
# deterministic parser, so each file must come back `unreadable` — the verdict
# that routes a document's text to the model in full — and its text must
# actually extract, carrying the same figures as the native document.
BUNDLES_XL = Path(__file__).resolve().parent / "bundles_excel"

expect("excel: the same bundles as the native kit",
       sorted(p.name for p in BUNDLES_XL.iterdir()),
       sorted(p.name for p in BUNDLES.iterdir()))

for folder in sorted(p.name for p in BUNDLES_XL.iterdir() if p.is_dir()):
    native = sorted(f.stem for f in (BUNDLES / folder).iterdir() if f.is_file())
    twins = sorted(f.stem for f in (BUNDLES_XL / folder).iterdir() if f.is_file())
    expect(f"excel {folder}: one .xlsx per document", twins, native)
    expect(f"excel {folder}: every file is .xlsx",
           sorted({f.suffix for f in (BUNDLES_XL / folder).iterdir()}), [".xlsx"])

xl_schedule = BUNDLES_XL / "home_loan_negative" / "03_emi_schedule.xlsx"
res = lx.extract_document(xl_schedule)
expect("excel: not reconciled in code — there is no Excel parser",
       res.status, "unreadable")
expect("excel: the reason is recorded",
       {e["reason"] for e in res.exceptions}, {"could_not_open"})

try:
    import pandas                                    # noqa: F401
    import openpyxl                                  # noqa: F401
except ImportError:
    print("note: pandas/openpyxl not installed — skipping the Excel text "
          "checks (pip install pandas openpyxl)\n")
else:
    text, err = lp.extract_text(xl_schedule)
    expect("excel: text extraction succeeds", err, "")
    flat = text.replace(",", "")
    expect("excel: the tampered row 7 balance reaches the model",
           "3123550.8" in flat, True)
    expect("excel: the amortised EMI reaches the model",
           "33222.37" in flat, True)

    letter, err = lp.extract_text(
        BUNDLES_XL / "home_loan_negative" / "01_sanction_letter.xlsx")
    expect("excel: the sanction letter extracts", err, "")
    expect("excel: it carries the same understated EMI as the PDF",
           "30822.37" in letter.replace(",", ""), True)

    slip, err = lp.extract_text(
        BUNDLES_XL / "vehicle_loan_negative" / "02_salary_slip.xlsx")
    expect("excel: the payslip extracts", err, "")
    expect("excel: it carries the same short deductions total",
           "9000" in slip.replace(",", "").replace(".0", ""), True)


# ── report ───────────────────────────────────────────────────────────────────
if failures:
    print(f"FAILED {len(failures)} of {checks} checks\n")
    for f_ in failures:
        print("  x " + f_)
    print("\nRebuild with: python demo_kit/loan_kit/build_kit.py")
    sys.exit(1)

print(f"OK - {checks} checks passed. The kit matches EXPECTED.md.")
