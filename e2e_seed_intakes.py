import sys, email.policy
from email.message import EmailMessage
sys.path.insert(0, ".")
from email_ingest import EmailIngestConfig, EmailIngestor

def fake_pdf(*lines, pages=1):
    b = b"%PDF-1.4\n" + b"".join(b"<</Type /Page>>\n" for _ in range(pages))
    for ln in lines: b += b"BT (" + ln.encode() + b") Tj ET\n"
    return b + b"%%EOF"

DOCS = [("application.pdf", fake_pdf("Loan Application","Applicant Name: R. Sharma","Loan Amount: 45,00,000","Tenure: 240 months")),
        ("pan.pdf", fake_pdf("Income Tax Department","Permanent Account Number")),
        ("salary.pdf", fake_pdf("Salary Slip April","Gross Salary: 1,80,000","Net Pay: 1,42,000")),
        ("deed.pdf", fake_pdf("Sale Deed","Property Schedule: Plot 14, Whitefield"))]

def mail(subject, sender="ops@meridiannbfc.example", docs=DOCS, body="Please process the attached home loan pack for applicant R. Sharma."):
    m = EmailMessage()
    m["From"] = f"Meridian Ops <{sender}>"; m["To"] = "docs@prefectos.ai"
    m["Subject"] = subject; m["Message-ID"] = f"<{subject[:10]}@e2e>"
    m["Authentication-Results"] = "mx.google.com; spf=pass dkim=pass dmarc=pass"
    m.set_content(body)
    for n,p in docs:
        m.add_attachment(p, maintype="application", subtype="pdf", filename=n)
    return m

cfg = EmailIngestConfig.load("email_ingest_config.json")
ing = EmailIngestor(cfg, imap_factory=lambda: None)
r1 = ing.handle_message(mail("Home loan pack — applicant 4412"))
# second pack: different content so hashes differ
DOCS2 = [(n, p + b"\n% applicant 5518") for n,p in DOCS]
r2 = ing.handle_message(mail("Home loan pack — applicant 5518", docs=DOCS2,
        body="Second applicant pack. Salary slips for last 3 months attached."))
print("seeded:", r1.get("intake_id"), r2.get("intake_id"), "accepted:", r1["accepted"], r2["accepted"])

# KYC pack from acme (route product = kyc) — will hit the governance denial
KYC_DOCS = [("kyc_form.pdf", fake_pdf("KYC Form","Know Your Customer","Date of Birth: 04/07/1991")),
            ("pan2.pdf", fake_pdf("Income Tax Department","Permanent Account Number","ACME PAN"))]
r3 = ing.handle_message(mail("KYC pack — Acme customer 0091",
        sender="loans@acmesfb.example", docs=KYC_DOCS,
        body="KYC refresh pack for customer 0091."))
print("kyc seeded:", r3.get("intake_id"), "accepted:", r3["accepted"])
