"""Build positive / negative email-intake document packs per loan product.

    python samples/build_email_packs.py            # -> samples/email_packs/<pack>/
    python samples/build_email_packs.py --verify   # + run the real validator & extractor

The documents come from demo_kit/loan_kit/application_docs.py — the same
application-stage bundles the demo kit ships under demo_kit/loan_kit/bundles
— rendered with the kit's dependency-free PDF writer. Here they are laid out
as email packs: a folder per pack with a README naming the intake mailbox
and the subject line (the connector reads the product from the subject).

    home_loan_positive      home_loan_negative
    vehicle_loan_positive   vehicle_loan_negative
    personal_loan_positive  personal_loan_negative

Every pack is a different fictional applicant, so the connector's SHA-256
de-duplication never collides between packs. Every page is stamped SPECIMEN.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "demo_kit" / "loan_kit"))
import application_docs as docs            # noqa: E402
import application_kit as kit              # noqa: E402

OUT = ROOT / "samples" / "email_packs"
MAILBOX = "loandocs@prefectos.ai"
SUBJECT = {"home_loan": "Home Loan application - {name}",
           "vehicle_loan": "Vehicle Loan application - {name}",
           "personal_loan": "Personal Loan application - {name}"}


def pack_name(kit_name: str) -> str:
    return kit_name.replace("_application", "")


def build() -> dict[str, dict]:
    built = {}
    expected_md = ["# Expected outcomes for the email-intake sample packs", "",
                   "Send every PDF of a pack in ONE email to the mailbox shown, with the suggested subject",
                   "(the product is read from the subject). Each pack is a different fictional applicant.", ""]
    for kit_name, (product, fn) in docs.PACK_SPECS.items():
        pack = pack_name(kit_name)
        a, documents, expect = fn()
        folder = OUT / pack
        if folder.exists():
            for f in folder.iterdir():
                f.unlink()
        for name, pages in documents.items():
            kit.write_pdf(folder / name, pages)
        subject = SUBJECT[product].format(name=a.name)
        (folder / "README.txt").write_text(
            f"{pack}  -  applicant {a.name} (fictional)\n"
            f"Send to : {MAILBOX}\nSubject : {subject}\nAttach  : every PDF in this folder\n\n"
            f"Expected decision: {expect[0]}\n" + "".join(f"  - {x}\n" for x in expect[1:]), encoding="utf-8")
        built[pack] = {"product": product, "applicant": a, "docs": list(documents),
                       "expect": expect, "mailbox": MAILBOX, "subject": subject}
        expected_md += [f"## {pack} - {a.name}", f"Send to **{MAILBOX}**, subject `{subject}`", "",
                        f"**Expected decision: {expect[0]}**", *(f"- {x}" for x in expect[1:]), ""]
    (OUT / "EXPECTED.md").write_text("\n".join(expected_md), encoding="utf-8")
    return built


def verify(built: dict[str, dict]) -> bool:
    from email_validation import DocumentValidator, extract_pdf_text
    from loan_extractors import extract_document, TYPE_MARKERS
    v = DocumentValidator.load(ROOT / "doc_templates.json")
    ok = True
    for pack, info in built.items():
        print(f"\n{pack}  ({info['applicant'].name})  ->  {info['mailbox']}")
        classified = []
        for name in info["docs"]:
            payload = (OUT / pack / name).read_bytes()
            c = v.classify(name, payload)
            classified.append(c)
            print(f"  {'OK ' if c.doc_type else 'BAD'} {name:<44} {c.doc_type or c.detail[:60]}")
            ok &= bool(c.doc_type)
            text = extract_pdf_text(payload)[0].upper()
            for tname, marker in TYPE_MARKERS:
                if marker in text and not (tname == "salary_slip" and "income_proof" in name):
                    print(f"  BAD {name}: contains extractor marker {marker!r}")
                    ok = False
        complete, missing = v.check_set(info["product"], classified)
        print(f"  document set for {info['product']}: {'COMPLETE' if complete else 'INCOMPLETE - missing ' + ', '.join(missing)}")
        ok &= complete
        slip = next(n for n in info["docs"] if "income_proof" in n)
        r = extract_document(OUT / pack / slip)
        print(f"  extractor: {r.doc_type} status={r.status} gross={r.fields.get('gross')} "
              f"net={r.fields.get('net_pay')} exceptions={[e['reason'] for e in r.exceptions]}")
        ok &= r.doc_type == "salary_slip" and "net_pay" in r.fields
        if pack == "home_loan_negative":
            ok &= any(e["reason"] == "gross_mismatch" for e in r.exceptions)
        else:
            ok &= r.status == "clean"
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    built = build()
    print(f"wrote {sum(len(i['docs']) for i in built.values())} PDFs in {len(built)} packs under {OUT}")
    if args.verify:
        good = verify(built)
        print("\nALL PACKS VERIFIED" if good else "\nVERIFICATION FAILED")
        raise SystemExit(0 if good else 1)
