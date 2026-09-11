"""Generate KYC and account-statement sample packs for email-intake testing.

Loan packs (positive/negative per product) come from samples/build_email_packs.py.

Writes one folder per product under samples/email_packs/<product>/ with the
PDFs that satisfy that product's required document set (doc_templates.json),
plus a README saying which intake mailbox to send them to. Every document is
fictional test data for a made-up applicant and is watermarked as such.

Run:  python tests/make_sample_packs.py            # -> samples/email_packs/
      python tests/make_sample_packs.py --verify   # also run the validator
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "samples" / "email_packs"

APPLICANT = {
    "name": "Rahul Sharma", "dob": "14-03-1988", "pan": "ABCPS1234K",
    "aadhaar": "XXXX XXXX 4321", "address": "Flat 302, Lakeview Residency, Whitefield, Bengaluru 560066",
    "employer": "Nimbus Analytics Pvt Ltd", "phone": "+91 98450 12345",
    "account": "50100234567890", "ifsc": "HDFC0001234",
}


def _page(c, title, lines, footer=""):
    w, h = A4
    c.setFont("Helvetica-Bold", 16); c.drawString(20 * mm, h - 25 * mm, title)
    c.setFont("Helvetica", 8); c.setFillGray(0.45)
    c.drawString(20 * mm, h - 31 * mm,
                 "SAMPLE DOCUMENT — fictional test data for PrefectOS email-intake testing. Not a real record.")
    c.setFillGray(0); c.setFont("Helvetica", 10.5)
    y = h - 45 * mm
    for ln in lines:
        if ln == "":
            y -= 4 * mm; continue
        if ln.startswith("## "):
            c.setFont("Helvetica-Bold", 11.5); c.drawString(20 * mm, y, ln[3:]); c.setFont("Helvetica", 10.5)
        else:
            c.drawString(20 * mm, y, ln)
        y -= 6.2 * mm
        if y < 25 * mm:
            c.showPage(); c.setFont("Helvetica", 10.5); y = h - 25 * mm
    if footer:
        c.setFont("Helvetica-Oblique", 8); c.setFillGray(0.45); c.drawString(20 * mm, 15 * mm, footer); c.setFillGray(0)
    c.showPage()


def pdf(path: Path, pages: list[tuple[str, list[str]]], footer=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    for title, lines in pages:
        _page(c, title, lines, footer)
    c.save()


A = APPLICANT


def application_form(product_label, amount, tenure, extra):
    return [("LOAN APPLICATION FORM", [
        f"Product applied: {product_label}",
        f"Applicant name: {A['name']}",
        f"Date of birth: {A['dob']}        PAN: {A['pan']}",
        f"Residential address: {A['address']}",
        f"Mobile: {A['phone']}        Email: rahul.sharma@example.com",
        "",
        "## Loan requested",
        f"Loan amount: INR {amount}",
        f"Tenure: {tenure}",
        "Purpose: " + extra["purpose"],
        "",
        "## Employment",
        f"Employer: {A['employer']}        Designation: Senior Data Engineer",
        "Employment type: Salaried        Years in current job: 4",
        "Gross monthly income: INR 1,80,000        Net monthly income: INR 1,42,000",
        "",
        "## Existing obligations",
        "Credit card outstanding: INR 45,000        Other EMIs: INR 12,500 / month",
        "",
        "## Declaration",
        "I declare that the information given in this loan application is true and complete.",
        f"Signature: {A['name']}        Date: 01-09-2026",
    ]), ("LOAN APPLICATION FORM — Annexure A", [
        "## Co-applicant / guarantor",
        "Name: Priya Sharma        Relationship: Spouse        Income: INR 95,000 / month",
        "",
        "## References",
        "1. Anil Mehta, Bengaluru, +91 98860 22334",
        "2. Sunita Rao, Bengaluru, +91 99000 55667",
        "",
        "## Documents enclosed with this loan application",
    ] + [f"  - {d}" for d in extra["enclosed"]])]


def identity_proof():
    return [("PERMANENT ACCOUNT NUMBER CARD", [
        "INCOME TAX DEPARTMENT        GOVT. OF INDIA",
        "",
        f"Permanent Account Number: {A['pan']}",
        f"Name: {A['name'].upper()}",
        "Father's name: SURESH SHARMA",
        f"Date of birth: {A['dob']}",
        "",
        "Signature: Rahul Sharma",
    ]), ("AADHAAR — Unique Identification Authority of India", [
        f"Aadhaar number: {A['aadhaar']}",
        f"Name: {A['name']}        DOB: {A['dob']}        Gender: Male",
        f"Address: {A['address']}",
        "",
        "Aadhaar is a proof of identity, not of citizenship.",
    ])]


def income_proof():
    rows = []
    for month in ("June 2026", "July 2026", "August 2026"):
        rows.append((f"SALARY SLIP — {month}", [
            f"Employer: {A['employer']}",
            f"Employee: {A['name']}        Employee ID: NA-2093        Designation: Senior Data Engineer",
            f"PAN: {A['pan']}        Bank A/c: {A['account']}",
            "",
            "## Earnings",
            "Basic salary            INR 90,000",
            "House rent allowance    INR 45,000",
            "Special allowance       INR 45,000",
            "Gross salary            INR 1,80,000",
            "",
            "## Deductions",
            "Provident fund          INR 10,800",
            "Professional tax        INR 200",
            "Income tax (TDS)        INR 27,000",
            "Total deductions        INR 38,000",
            "",
            "Net pay                 INR 1,42,000",
            "",
            "This pay slip is computer generated and does not require a signature.",
        ]))
    rows.append(("FORM 16 — Certificate under section 203 of the Income-tax Act (FY 2025-26)", [
        f"Employer: {A['employer']}        TAN: BLRN12345A",
        f"Employee: {A['name']}        PAN: {A['pan']}",
        "",
        "Gross salary (total income from salary)     INR 21,60,000",
        "Total income                                INR 19,85,000",
        "Tax deducted at source                      INR 3,24,000",
        "",
        "Verified by: Meera Iyer, Head of Finance",
    ]))
    return rows


def property_document():
    return [("SALE DEED", [
        "THIS SALE DEED is executed on 20-08-2026 at Bengaluru",
        "",
        "BETWEEN",
        "Mr. Venkatesh Gowda, s/o late Krishnappa (the VENDOR)",
        "AND",
        f"Mr. {A['name']}, s/o Suresh Sharma (the PURCHASER)",
        "",
        "## Property schedule",
        "All that piece and parcel of residential apartment bearing No. 302, third floor,",
        "'Lakeview Residency', Whitefield, Bengaluru 560066, measuring 1,240 sq ft super",
        "built-up area with one covered car park, together with undivided share of land.",
        "Khata No. 118/302, BBMP Mahadevapura zone.",
        "",
        "## Consideration",
        "Total sale consideration: INR 95,00,000 (Rupees ninety-five lakh only)",
        "",
        "## Encumbrance",
        "The vendor declares the property is free from all encumbrances, charges, and",
        "litigation; encumbrance certificate for 2010-2026 is annexed.",
    ]), ("SALE DEED — Annexure: Encumbrance Certificate", [
        "Sub-Registrar Office, Varthur",
        "Encumbrance certificate for the period 01-01-2010 to 15-08-2026",
        "Property: Apartment 302, Lakeview Residency, Whitefield (Khata 118/302)",
        "",
        "No encumbrances found for the above period.",
    ])]


def kyc_form():
    return [("KYC FORM — Know Your Customer", [
        "Customer identification form (individual)",
        "",
        f"Name: {A['name']}",
        f"Date of birth: {A['dob']}        Gender: Male        Nationality: Indian",
        f"PAN: {A['pan']}        Aadhaar: {A['aadhaar']}",
        f"Mobile: {A['phone']}        Email: rahul.sharma@example.com",
        "",
        "## Address proof",
        f"Current address: {A['address']}",
        "Address proof submitted: Aadhaar",
        "",
        "## Identity proof",
        "Identity proof submitted: PAN card, Aadhaar",
        "",
        "## Declaration",
        "I hereby declare that the details furnished above are true and correct.",
        f"Signature: {A['name']}        Date: 01-09-2026",
    ])]


def bank_statement():
    txns = [
        ("01-08-2026", "Opening balance", "", "", "2,14,500.00"),
        ("01-08-2026", "SALARY NIMBUS ANALYTICS", "", "1,42,000.00", "3,56,500.00"),
        ("03-08-2026", "UPI/RENT/AUG", "38,000.00", "", "3,18,500.00"),
        ("05-08-2026", "EMI HDFC CAR LOAN", "12,500.00", "", "3,06,000.00"),
        ("09-08-2026", "CARD PAYMENT", "45,000.00", "", "2,61,000.00"),
        ("14-08-2026", "UPI/GROCERIES", "6,240.00", "", "2,54,760.00"),
        ("20-08-2026", "NEFT/INSURANCE PREMIUM", "18,000.00", "", "2,36,760.00"),
        ("31-08-2026", "Closing balance", "", "", "2,36,760.00"),
    ]
    lines = [
        "HDFC Bank — Savings account statement",
        f"Account holder: {A['name']}",
        f"Account number: {A['account']}        IFSC: {A['ifsc']}        Branch: Whitefield",
        "Statement period: 01-08-2026 to 31-08-2026",
        "",
        "Date         Transaction description          Debit        Credit       Balance",
    ]
    for d, desc, dr, cr, bal in txns:
        lines.append(f"{d:<12} {desc:<32} {dr:>10}   {cr:>10}   {bal:>12}")
    lines += ["", "Opening balance: INR 2,14,500.00        Closing balance: INR 2,36,760.00",
              "Total debits: INR 1,19,740.00 (5 transactions)        Total credits: INR 1,42,000.00 (1 transaction)"]
    return [("ACCOUNT STATEMENT", lines)]


PACKS = {

    "kyc": {
        "mailbox": "kycdocs@prefectos.ai",
        "docs": {
            "01_kyc_form.pdf": kyc_form(),
            "02_identity_proof_pan_aadhaar.pdf": identity_proof(),
        },
    },
    "statement": {
        "mailbox": "creditdocs@prefectos.ai",
        "docs": {
            "01_bank_account_statement.pdf": bank_statement(),
        },
    },
}


def build() -> list[Path]:
    written = []
    for product, spec in PACKS.items():
        folder = OUT / product
        for name, pages in spec["docs"].items():
            pdf(folder / name, pages, footer=f"Sample pack for email-intake testing · {A['name']} is a fictional applicant")
            written.append(folder / name)
        (folder / "README.txt").write_text(
            f"Sample {product} pack — fictional applicant {A['name']}.\n"
            f"Attach every PDF in this folder to ONE email and send it to: {spec['mailbox']}\n"
            f"Subject suggestion: {product.replace('_', ' ').title()} application - {A['name']}\n",
            encoding="utf-8")
    return written


def verify() -> bool:
    from email_validation import DocumentValidator
    v = DocumentValidator.load(ROOT / "doc_templates.json")
    ok = True
    for product, spec in PACKS.items():
        classified = []
        print(f"\n{product}  ->  {spec['mailbox']}")
        for name in spec["docs"]:
            payload = (OUT / product / name).read_bytes()
            cls = v.classify(name, payload)
            classified.append(cls)
            flag = "OK " if cls.doc_type else "BAD"
            print(f"  {flag} {name:<40} {cls.doc_type or cls.detail}")
            ok &= bool(cls.doc_type)
        complete, missing = v.check_set(product, classified)
        print(f"  document set {'COMPLETE' if complete else 'INCOMPLETE — missing ' + ', '.join(missing)}")
        ok &= complete
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    files = build()
    print(f"wrote {len(files)} PDFs under {OUT}")
    if args.verify:
        raise SystemExit(0 if verify() else 1)
