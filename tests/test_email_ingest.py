"""Offline tests for the email intake feature (connector + validation +
review + queue routing + settings). No network, no mailbox, no PDF libs
required (dependency-free literal-string PDF text fallback).

Run:  python -m pytest tests/test_email_ingest.py -q
"""
from __future__ import annotations

import hashlib
import json
import sys
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from email_ingest import (  # noqa: E402
    EmailAuditLog,
    EmailIngestConfig,
    EmailIngestor,
    MailboxRoute,
    validate_message,
)
from email_validation import (  # noqa: E402
    DocumentValidator,
    is_valid_address_syntax,
    parse_authentication_results,
    validate_sender_authenticity,
)

TEMPLATES = DocumentValidator.load(
    Path(__file__).resolve().parents[1] / "doc_templates.json")


def fake_pdf(*lines: str, pages: int = 1) -> bytes:
    """Minimal PDF-looking bytes whose text the literal-string fallback
    extractor can read. Real deployments use pdfplumber on real PDFs."""
    body = b"%PDF-1.4\n"
    body += b"".join(b"<</Type /Page>>\n" for _ in range(pages))
    for ln in lines:
        body += b"BT (" + ln.encode() + b") Tj ET\n"
    return body + b"%%EOF"


APPLICATION = fake_pdf("Loan Application", "Applicant Name: R. Sharma",
                       "Loan Amount: 45,00,000", "Tenure: 240 months")
PAN_CARD = fake_pdf("Income Tax Department", "Permanent Account Number")
SALARY = fake_pdf("Salary Slip April", "Gross Salary: 1,80,000",
                  "Net Pay: 1,42,000")
DEED = fake_pdf("Sale Deed", "Property Schedule: Plot 14, Whitefield")
RANDOM_PDF = fake_pdf("Meeting notes", "agenda item one")

FULL_PACK = [("application.pdf", APPLICATION), ("pan.pdf", PAN_CARD),
             ("salary.pdf", SALARY), ("deed.pdf", DEED)]


def make_config(**over) -> EmailIngestConfig:
    base = dict(
        imap_host="imap.test", imap_user="docs@test",
        templates_file=str(Path(__file__).resolve().parents[1]
                           / "doc_templates.json"),
        routes=[MailboxRoute(client_id="meridian_nbfc",
                             senders=["ops@meridian.test",
                                      "*@bulk.meridian.test"],
                             product="home_loan")],
    )
    base.update(over)
    return EmailIngestConfig(**base)


def make_mail(sender="ops@meridian.test", attachments=None,
              subject="Loan docs", auth="spf=pass dkim=pass dmarc=pass"):
    msg = EmailMessage()
    msg["From"] = f"Ops Team <{sender}>"
    msg["To"] = "docs@test"
    msg["Subject"] = subject
    msg["Message-ID"] = "<t1@test>"
    if auth:
        msg["Authentication-Results"] = f"mx.test; {auth}"
    msg.set_content("Please process the attached.")
    for name, payload in (attachments or []):
        msg.add_attachment(payload, maintype="application", subtype="pdf",
                           filename=name)
    return msg


def run(mail, cfg=None, seen=None):
    cfg = cfg or make_config()
    return validate_message(mail, cfg, seen or set(),
                            TEMPLATES if cfg.templates_file else None)


# ── Stage 1: sender validity ───────────────────────────────────────────
def test_address_syntax():
    assert is_valid_address_syntax("ops@meridian.test")
    for bad in ["not-an-email", "a b@x.com", "a@b", "a..b@x.com", "@x.com", ""]:
        assert not is_valid_address_syntax(bad), bad


def test_auth_results_parsing_and_verdict():
    m = make_mail(auth="spf=fail dkim=fail dmarc=fail")
    assert parse_authentication_results(m) == {
        "spf": "fail", "dkim": "fail", "dmarc": "fail"}
    ok, why = validate_sender_authenticity(m, "ops@meridian.test")
    assert not ok and why.startswith("sender_auth_failed")


def test_spoofed_sender_rejected_despite_allowlist():
    v = run(make_mail(attachments=FULL_PACK, auth="spf=fail dkim=fail"))
    assert not v.ok and v.reason.startswith("sender_auth_failed")


def test_missing_auth_header_rejected_when_required():
    v = run(make_mail(attachments=FULL_PACK, auth=None))
    assert not v.ok and v.reason == "no_authentication_results"


def test_auth_not_required_mode():
    cfg = make_config(require_authentication=False)
    v = run(make_mail(attachments=FULL_PACK, auth=None), cfg)
    assert v.ok


def test_unknown_sender_still_rejected_first():
    v = run(make_mail(sender="attacker@evil.test", attachments=FULL_PACK))
    assert not v.ok and v.reason == "sender_not_allowlisted"


# ── Stage 2: template validation ───────────────────────────────────────
def test_classification_assigns_doc_types():
    v = run(make_mail(attachments=FULL_PACK))
    assert v.ok
    assert v.doc_types == {"application.pdf": "application_form",
                           "pan.pdf": "identity_proof",
                           "salary.pdf": "income_proof",
                           "deed.pdf": "property_document"}


def test_non_template_pdf_rejected():
    v = run(make_mail(attachments=FULL_PACK + [("notes.pdf", RANDOM_PDF)]))
    assert v.ok and "notes.pdf:template_mismatch" in v.reason
    assert v.doc_types["notes.pdf"] is None
    assert len(v.attachments) == 4          # notes.pdf dropped


def test_not_a_real_pdf_rejected():
    v = run(make_mail(attachments=FULL_PACK
                      + [("fake.pdf", b"MZ this is an exe")]))
    assert v.ok and "fake.pdf:not_a_pdf" in v.reason


# ── Stage 3: document set ──────────────────────────────────────────────
def test_incomplete_home_loan_pack_rejected_with_missing_list():
    v = run(make_mail(attachments=[("application.pdf", APPLICATION),
                                   ("pan.pdf", PAN_CARD)]))
    assert not v.ok
    assert v.reason.startswith("incomplete_document_set")
    assert set(v.missing_docs) == {"income_proof", "property_document"}


def test_complete_pack_accepted():
    v = run(make_mail(attachments=FULL_PACK))
    assert v.ok and v.missing_docs == []


def test_set_not_enforced_mode():
    cfg = make_config(enforce_document_set=False)
    v = run(make_mail(attachments=[("application.pdf", APPLICATION)]), cfg)
    assert v.ok


def test_route_without_product_skips_set_check():
    cfg = make_config(routes=[MailboxRoute(client_id="internal",
                                           senders=["ops@meridian.test"])])
    v = run(make_mail(attachments=[("pan.pdf", PAN_CARD)]), cfg)
    assert v.ok


# ── Connector behavior ─────────────────────────────────────────────────
def test_duplicate_doc_dropped_making_pack_incomplete():
    # application.pdf was already processed once → dropped as duplicate →
    # the remaining pack is missing application_form → rejected with that.
    seen = {hashlib.sha256(APPLICATION).hexdigest()}
    v = run(make_mail(attachments=FULL_PACK), seen=seen)
    assert not v.ok
    assert v.reason == "incomplete_document_set:missing=application_form"
    assert v.missing_docs == ["application_form"]


def test_path_traversal_filename_stripped():
    v = run(make_mail(attachments=[("../../etc/x.pdf", APPLICATION),
                                   ("pan.pdf", PAN_CARD),
                                   ("salary.pdf", SALARY),
                                   ("deed.pdf", DEED)]))
    assert v.ok and "x.pdf" in v.doc_types


def test_audit_chain_verifies_and_detects_tamper(tmp_path):
    log = EmailAuditLog(tmp_path / "audit.jsonl")
    log.record("email_accepted", sender="a@b", n_docs=1)
    log.record("batch_submitted", batch_id="xyz")
    assert log.verify()[0]
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    rec = json.loads(lines[0]); rec["sender"] = "tampered@evil"
    lines[0] = json.dumps(rec, sort_keys=True)
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    assert not EmailAuditLog(tmp_path / "audit.jsonl").verify()[0]


def test_end_to_end_submit_dedup_and_ledger(tmp_path):
    calls = []

    def fake_submit(api, client_id, files):
        calls.append((client_id, sorted(n for n, _ in files)))
        return {"batch_id": "b123", "accepted": len(files)}

    ing = EmailIngestor(make_config(review_mode=False),
                        imap_factory=lambda: None,
                        submitter=fake_submit, state_dir=tmp_path)
    out = ing.handle_message(make_mail(attachments=FULL_PACK))
    assert out["accepted"] and out["batch_id"] == "b123"
    assert calls == [("meridian_nbfc",
                      ["application.pdf", "deed.pdf", "pan.pdf", "salary.pdf"])]

    out2 = ing.handle_message(make_mail(attachments=FULL_PACK))
    assert not out2["accepted"] and len(calls) == 1     # replay blocked

    events = [json.loads(l)["event"] for l in
              (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events == ["email_accepted", "batch_submitted", "email_rejected"]
    assert ing.audit.verify()[0]


def test_submit_failure_is_ledgered_not_lost(tmp_path):
    def broken_submit(api, client_id, files):
        raise OSError("connection refused")

    ing = EmailIngestor(make_config(review_mode=False),
                        imap_factory=lambda: None,
                        submitter=broken_submit, state_dir=tmp_path)
    out = ing.handle_message(make_mail(attachments=FULL_PACK))
    assert not out["accepted"] and out["reason"] == "submit_failed"
    assert ing.seen == set()            # retry possible next cycle


# ── Review mode: park → inspect → process to queue ────────────────────
def test_review_mode_parks_email_with_body_and_docs(tmp_path):
    ing = EmailIngestor(make_config(review_mode=True),
                        imap_factory=lambda: None,
                        submitter=lambda *a: (_ for _ in ()).throw(
                            AssertionError("must not auto-submit")),
                        state_dir=tmp_path)
    out = ing.handle_message(make_mail(attachments=FULL_PACK))
    assert out["accepted"] and out["batch_id"] is None
    intake_id = out["intake_id"]

    from email_review import PendingStore
    store = PendingStore(tmp_path / "pending")
    m = store.manifest(intake_id)
    assert m["status"] == "pending"
    assert "Please process the attached." in m["body_text"]
    assert {d["name"] for d in m["documents"]} == \
        {"application.pdf", "pan.pdf", "salary.pdf", "deed.pdf"}
    assert {d["doc_type"] for d in m["documents"]} == \
        {"application_form", "identity_proof", "income_proof",
         "property_document"}
    assert store.doc_path(intake_id, "pan.pdf").read_bytes() == PAN_CARD
    with pytest.raises(KeyError):
        store.doc_path(intake_id, "../../secrets.txt")

    events = [json.loads(l)["event"] for l in
              (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events == ["email_accepted", "email_pending_review"]


def test_queue_resolution_by_product():
    from email_review import resolve_queue
    qmap = {"home_loan": {"api": "http://127.0.0.1:8000/loan/ingest"},
            "kyc": {"api": "http://127.0.0.1:8000/account/ingest"}}
    assert resolve_queue("home_loan", "http://d/ingest", qmap) == \
        ("http://127.0.0.1:8000/loan/ingest", "home_loan")
    assert resolve_queue("kyc", "http://d/ingest", qmap) == \
        ("http://127.0.0.1:8000/account/ingest", "kyc")
    assert resolve_queue("statement", "http://d/ingest", qmap) == \
        ("http://d/ingest", "statement")
    assert resolve_queue(None, "http://d/ingest", qmap) == \
        ("http://d/ingest", "general")


def test_process_intake_routes_to_queue_and_seals(tmp_path, monkeypatch):
    ing = EmailIngestor(make_config(review_mode=True),
                        imap_factory=lambda: None, state_dir=tmp_path)
    intake_id = ing.handle_message(make_mail(attachments=FULL_PACK))["intake_id"]

    import email_review
    monkeypatch.setattr(email_review, "store",
                        email_review.PendingStore(tmp_path / "pending"))
    monkeypatch.setattr(email_review, "STATE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(email_review, "_submit",
                        lambda api, uid, files: (calls.append((api, uid,
                            sorted(n for n, _ in files)))
                            or {"batch_id": "b777", "accepted": len(files)}))
    cfg = make_config(review_mode=True,
                      queues={"home_loan": {"api": "http://q/loan"}})
    monkeypatch.setattr(email_review, "_config", lambda: cfg)
    monkeypatch.setattr(email_review, "_audit",
                        lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))

    res = email_review.process_intake(intake_id, approver="sarah.jenkins")
    assert res == {"intake_id": intake_id, "status": "processed",
                   "queue": "home_loan", "batch_id": "b777"}
    assert calls == [("http://q/loan", "meridian_nbfc::home_loan",
                      ["application.pdf", "deed.pdf", "pan.pdf",
                       "salary.pdf"])]
    from fastapi import HTTPException
    with pytest.raises(HTTPException):          # idempotent: no double-run
        email_review.process_intake(intake_id, approver="sarah.jenkins")

    events = [json.loads(l)["event"] for l in
              (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events[-1] == "intake_processed"
    assert EmailAuditLog(tmp_path / "email_audit.jsonl").verify()[0]


# ── Settings endpoints (valid inboxes + templates) ────────────────────
def _wire_settings(tmp_path, monkeypatch):
    import email_ingest, email_review
    cfg_path = tmp_path / "email_ingest_config.json"
    tpl_path = tmp_path / "doc_templates.json"
    src = Path(__file__).resolve().parents[1]
    cfg_path.write_text((src / "email_ingest_config.json").read_text()
                        .replace("doc_templates.json", str(tpl_path)
                                 .replace("\\", "/")))
    tpl_path.write_text((src / "doc_templates.json").read_text())
    monkeypatch.setattr(email_ingest, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(email_review, "STATE_DIR", tmp_path)
    monkeypatch.setattr(email_review, "_audit",
                        lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))
    return cfg_path, tpl_path


def test_settings_roundtrip_sealed(tmp_path, monkeypatch):
    import email_review
    from fastapi import HTTPException
    cfg_path, _ = _wire_settings(tmp_path, monkeypatch)

    s = email_review.get_settings()
    s["routes"].append({"client_id": "new_client", "product": "kyc",
                        "senders": ["kyc@newclient.example"]})
    assert email_review.put_settings(s, approver="sarah")["ok"]
    assert any(r["client_id"] == "new_client"
               for r in json.loads(cfg_path.read_text())["routes"])

    with pytest.raises(HTTPException):          # credentials never in config
        email_review.put_settings(s | {"password": "x"}, approver="sarah")

    events = [json.loads(l)["event"] for l in
              (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert "routes_updated" in events


def test_templates_roundtrip_validates_doc_sets(tmp_path, monkeypatch):
    import email_review
    from fastapi import HTTPException
    _wire_settings(tmp_path, monkeypatch)

    t = email_review.get_templates()
    assert email_review.put_templates(t, approver="sarah")["ok"]

    t["document_sets"]["home_loan"].append("nonexistent_type")
    with pytest.raises(HTTPException):
        email_review.put_templates(t, approver="sarah")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
