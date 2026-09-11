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
    cfg = make_config(review_mode=True, processing_engine="batch",
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


# ── Multi-mailbox: dedicated per-client inboxes ────────────────────────
from email_ingest import MailboxSpec, MailboxAuthError, DEFAULT_MAILBOX_ID  # noqa: E402


class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for poll_once: one folder holding
    the given messages; records every move so tests can assert on it."""
    def __init__(self, messages, fail_select=False):
        self.msgs = {str(i + 1).encode(): m for i, m in enumerate(messages)}
        self.fail_select = fail_select
        self.moved: list[tuple[bytes, str]] = []
        self.selected = None

    def select(self, folder, readonly=False):
        self.selected = folder
        return ("NO" if self.fail_select else "OK", [b"1"])

    def search(self, charset, criterion):
        return ("OK", [b" ".join(self.msgs)])

    def fetch(self, msg_id, what):
        m = self.msgs[msg_id]
        if "HEADER.FIELDS" in what:
            hdr = "Message-ID: " + str(m.get("Message-ID", "")) + "\r\n\r\n"
            return ("OK", [(b"1 (BODY[HEADER] {n})", hdr.encode())])
        return ("OK", [(b"1 (RFC822 {n})", m.as_bytes())])

    def create(self, label): pass
    def copy(self, msg_id, label): self.moved.append((msg_id, label.decode()))
    def store(self, *a): pass

    def uid(self, cmd, *args):
        cmd = cmd.upper()
        if cmd == "SEARCH":
            return self.search(*args)
        if cmd == "FETCH":
            return self.fetch(*args)
        if cmd == "COPY":
            return self.copy(*args)
        if cmd == "STORE":
            return self.store(*args)
        raise AssertionError(cmd)
    def expunge(self): pass
    def logout(self): pass


def two_mailbox_config(**over) -> EmailIngestConfig:
    base = dict(
        imap_host="imap.test", imap_user="docs@test",
        templates_file=str(Path(__file__).resolve().parents[1]
                           / "doc_templates.json"),
        review_mode=False,
        mailboxes=[MailboxSpec(id="meridian", imap_host="outlook.office365.com",
                               imap_user="prefectos-intake@meridian.test",
                               auth="oauth_microsoft", tenant_id="t1",
                               oauth_client_id="app1",
                               secret_env="MERIDIAN_INTAKE_SECRET"),
                   MailboxSpec(id="acme", imap_host="imap.gmail.com",
                               imap_user="intake@acme.test",
                               secret_env="ACME_INTAKE_SECRET")],
        routes=[MailboxRoute(client_id="meridian_nbfc", product="home_loan",
                             senders=["*"], mailbox="meridian"),
                MailboxRoute(client_id="acme_sfb", product="home_loan",
                             senders=["*@acme.test"], mailbox="acme"),
                MailboxRoute(client_id="walkin", product="home_loan",
                             senders=["ops@meridian.test"])],   # default box
    )
    base.update(over)
    return EmailIngestConfig(**base)


def test_mailbox_spec_rejects_bad_values():
    with pytest.raises(ValueError):
        MailboxSpec(id="x", imap_host="h", imap_user="u", auth="basic")
    with pytest.raises(ValueError):
        MailboxSpec(id="x", imap_host="h", imap_user="u",
                    secret_env="hunter2!")            # must be an env var NAME
    with pytest.raises(ValueError):
        MailboxSpec(id="x", imap_host="h", imap_user="u", auth="oauth_microsoft")
    with pytest.raises(ValueError):                   # reserved id
        two_mailbox_config(mailboxes=[MailboxSpec(id="default", imap_host="h",
                                                  imap_user="u")]).validate_bindings()
    with pytest.raises(ValueError):                   # dangling binding
        two_mailbox_config(routes=[MailboxRoute(client_id="c", senders=["*"],
                                                mailbox="nope")]).validate_bindings()


def test_config_roundtrip_from_dict_and_polled_set():
    cfg = two_mailbox_config()
    assert [m.id for m in cfg.all_mailboxes()] == ["default", "meridian", "acme"]
    assert [m.id for m in cfg.polled_mailboxes()] == ["default", "meridian", "acme"]
    # a dedicated mailbox with no route bound is not polled
    cfg2 = two_mailbox_config(routes=[MailboxRoute(client_id="c", senders=["*"],
                                                   mailbox="acme")])
    assert [m.id for m in cfg2.polled_mailboxes()] == ["acme"]
    # legacy config without "mailboxes" still loads as a single default box
    legacy = EmailIngestConfig.from_dict({"imap_host": "h", "imap_user": "u",
                                          "routes": [{"client_id": "c",
                                                      "senders": ["a@b"]}]})
    assert legacy.routes[0].mailbox == DEFAULT_MAILBOX_ID
    assert [m.id for m in legacy.polled_mailboxes()] == ["default"]


def test_allowlist_is_scoped_to_the_mailbox_the_mail_arrived_in():
    cfg = two_mailbox_config()
    # ops@meridian.test is allowed into the DEFAULT box (walkin route)...
    assert cfg.route_for("ops@meridian.test", "default").client_id == "walkin"
    # ...and into meridian's own box only via its "*" wildcard route
    assert cfg.route_for("ops@meridian.test", "meridian").client_id == "meridian_nbfc"
    # ...but NOT into acme's dedicated box
    assert cfg.route_for("ops@meridian.test", "acme") is None
    assert cfg.route_for("anyone@random.test", "acme") is None
    assert cfg.route_for("kyc@acme.test", "acme").client_id == "acme_sfb"
    # unscoped lookup keeps the old first-match behaviour
    assert cfg.route_for("ops@meridian.test").client_id == "meridian_nbfc"

    v = validate_message(make_mail(sender="kyc@acme.test", attachments=FULL_PACK),
                         cfg, set(), TEMPLATES, mailbox_id="meridian")
    assert v.ok and v.client_id == "meridian_nbfc"     # wildcard box accepts
    v = validate_message(make_mail(sender="kyc@acme.test", attachments=FULL_PACK),
                         cfg, set(), TEMPLATES, mailbox_id="default")
    assert not v.ok and v.reason == "sender_not_allowlisted"


SECOND_PACK = [
    ("a.pdf", fake_pdf("Loan Application", "Applicant Name: A",
                       "Loan Amount: 1", "Tenure: 2")),
    ("p.pdf", fake_pdf("Income Tax Department", "Permanent Account Number", "x")),
    ("s.pdf", fake_pdf("Salary Slip", "Gross Salary: 1", "Net Pay: 1")),
    ("d.pdf", fake_pdf("Sale Deed", "Property Schedule: X")),
]


def test_poll_visits_every_mailbox_and_tags_the_ledger(tmp_path):
    cfg = two_mailbox_config()
    conns = {
        "default": FakeIMAP([make_mail(sender="ops@meridian.test",
                                       attachments=FULL_PACK)]),
        "meridian": FakeIMAP([make_mail(sender="applicant@gmail.test",
                                        attachments=SECOND_PACK)]),
        "acme": FakeIMAP([make_mail(sender="stranger@else.test",
                                    attachments=FULL_PACK)]),
    }
    submitted = []

    def submit(api, cid, files):
        submitted.append(cid)
        return {"batch_id": f"b-{cid}", "accepted": len(files)}

    ing = EmailIngestor(cfg, imap_factory=lambda spec: conns[spec.id],
                        submitter=submit, state_dir=tmp_path)
    stats = ing.poll_once()
    assert stats["scanned"] == 3 and stats["accepted"] == 2 and stats["rejected"] == 1
    assert stats["failed_mailboxes"] == []
    assert sorted(submitted) == ["meridian_nbfc", "walkin"]
    assert conns["meridian"].selected == "INBOX"
    assert conns["acme"].moved == [(b"1", "PrefectOS/Rejected")]
    assert conns["meridian"].moved == [(b"1", "PrefectOS/Processed")]

    recs = [json.loads(l) for l in
            (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    rejected_in = [r["mailbox"] for r in recs if r["event"] == "email_rejected"]
    assert rejected_in == ["acme"]
    assert all("mailbox" in r for r in recs if r["event"].startswith("email_"))
    status = ing.mailbox_status()
    assert set(status) == {"default", "meridian", "acme"}
    assert status["acme"]["rejected"] == 1 and status["acme"]["last_error"] is None
    assert ing.audit.verify()[0]


def test_one_failing_mailbox_does_not_stop_the_others(tmp_path):
    cfg = two_mailbox_config()
    ok_conn = FakeIMAP([make_mail(sender="kyc@acme.test", attachments=FULL_PACK)])

    def factory(spec):
        if spec.id == "meridian":
            raise MailboxAuthError("mailbox 'meridian': Microsoft token request failed (401)")
        if spec.id == "default":
            return FakeIMAP([], fail_select=True)
        return ok_conn

    ing = EmailIngestor(cfg, imap_factory=factory,
                        submitter=lambda api, cid, files: {"batch_id": "b1",
                                                           "accepted": len(files)},
                        state_dir=tmp_path)
    stats = ing.poll_once()
    assert sorted(stats["failed_mailboxes"]) == ["default", "meridian"]
    assert stats["accepted"] == 1 and stats["mailboxes"]["acme"]["accepted"] == 1
    assert "401" in stats["mailboxes"]["meridian"]["error"]
    events = [json.loads(l)["event"] for l in
              (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events.count("mailbox_poll_failed") == 2
    st = ing.mailbox_status()
    assert "401" in st["meridian"]["last_error"] and "last_ok" not in st["meridian"]
    assert st["acme"]["last_error"] is None

    # --mailbox filter polls only the named box
    stats2 = ing.poll_once(mailbox_ids=["acme"])
    assert list(stats2["mailboxes"]) == ["acme"]


def test_legacy_zero_arg_imap_factory_still_works(tmp_path):
    cfg = make_config(review_mode=False)
    conn = FakeIMAP([make_mail(attachments=FULL_PACK)])
    ing = EmailIngestor(cfg, imap_factory=lambda: conn,
                        submitter=lambda api, cid, files: {"batch_id": "b",
                                                           "accepted": 4},
                        state_dir=tmp_path)
    assert ing.poll_once()["accepted"] == 1


def test_secret_lookup_names_the_env_var_not_the_value(monkeypatch):
    from email_ingest import _secret_for
    spec = MailboxSpec(id="m", imap_host="h", imap_user="u", secret_env="ACME_X")
    monkeypatch.delenv("ACME_X", raising=False)
    with pytest.raises(MailboxAuthError) as ei:
        _secret_for(spec)
    assert "ACME_X" in str(ei.value)
    monkeypatch.setenv("ACME_X", "s3cret")
    assert _secret_for(spec) == "s3cret"
    assert spec.public()["secret_present"] is True
    assert "s3cret" not in json.dumps(spec.public())


def test_settings_accept_mailboxes_and_reject_pasted_credentials(tmp_path, monkeypatch):
    import email_review
    from fastapi import HTTPException
    cfg_path, _ = _wire_settings(tmp_path, monkeypatch)
    s = email_review.get_settings()
    s["mailboxes"] = s.get("mailboxes", []) + [{"id": "meridian", "imap_host": "outlook.office365.com",
                       "imap_user": "prefectos-intake@meridian.test",
                       "auth": "oauth_microsoft", "tenant_id": "t", "oauth_client_id": "a",
                       "secret_env": "MERIDIAN_INTAKE_SECRET"}]
    s["routes"].append({"client_id": "meridian_nbfc", "product": "home_loan",
                        "senders": ["*"], "mailbox": "meridian"})
    assert email_review.put_settings(s, approver="sarah")["ok"]
    saved = json.loads(cfg_path.read_text())
    assert "meridian" in [m["id"] for m in saved["mailboxes"]]

    bad = json.loads(json.dumps(s))
    bad["mailboxes"][0]["client_secret"] = "abc"          # credential pasted
    with pytest.raises(HTTPException) as ei:
        email_review.put_settings(bad, approver="sarah")
    assert "credentials" in ei.value.detail

    bad = json.loads(json.dumps(s))
    bad["routes"][-1]["mailbox"] = "ghost"                 # dangling binding
    with pytest.raises(HTTPException) as ei:
        email_review.put_settings(bad, approver="sarah")
    assert "ghost" in ei.value.detail

    bad = json.loads(json.dumps(s))
    bad["mailboxes"][0]["auth"] = "oauth_google"
    bad["mailboxes"][0]["secret_env"] = "/etc/key.json"    # value, not a name
    with pytest.raises(HTTPException):
        email_review.put_settings(bad, approver="sarah")

    monkeypatch.delenv("MERIDIAN_INTAKE_SECRET", raising=False)
    listed = email_review.list_mailboxes()["mailboxes"]
    assert listed[0]["id"] == "default" and "meridian" in [m["id"] for m in listed]
    mer = next(m for m in listed if m["id"] == "meridian")
    assert mer["routes"] == ["meridian_nbfc"] and mer["polled"] is True
    assert mer["secret_present"] is False


def test_mailbox_test_endpoint_reports_missing_secret(tmp_path, monkeypatch):
    import email_review
    from fastapi import HTTPException
    _wire_settings(tmp_path, monkeypatch)
    monkeypatch.delenv("DRAFT_SECRET", raising=False)
    r = email_review.test_mailbox({"mailbox": {"id": "draft", "imap_host": "127.0.0.1",
                                               "imap_port": 1, "imap_user": "u",
                                               "secret_env": "DRAFT_SECRET"}})
    assert r["ok"] is False and "DRAFT_SECRET" in r["error"]
    with pytest.raises(HTTPException):
        email_review.test_mailbox({"id": "nope"})
    with pytest.raises(HTTPException):
        email_review.test_mailbox({"mailbox": {"id": "d", "imap_host": "h",
                                               "imap_user": "u", "password": "x"}})


def test_kyc_form_naming_aadhaar_is_still_a_kyc_form():
    """A KYC form records the ID documents it was filled from, so it also
    satisfies identity_proof; the more specific template must win."""
    form = fake_pdf("KYC Form", "Know Your Customer", "Date of Birth: 14-03-1988",
                    "Aadhaar: XXXX XXXX 4321", "Address proof: Aadhaar")
    assert TEMPLATES.classify("kyc.pdf", form).doc_type == "kyc_form"
    # a plain ID document still classifies as identity proof
    assert TEMPLATES.classify("pan.pdf", PAN_CARD).doc_type == "identity_proof"
    complete, missing = TEMPLATES.check_set("kyc", [
        TEMPLATES.classify("kyc.pdf", form), TEMPLATES.classify("pan.pdf", PAN_CARD)])
    assert complete and not missing


def test_read_mail_is_still_picked_up_and_handled_only_once(tmp_path):
    """Someone opening the mail in webmail (\Seen) must not hide it from
    intake; and a mail left in the folder (move failed) is not re-handled."""
    cfg = make_config(review_mode=False)
    mail = make_mail(attachments=FULL_PACK)          # Message-ID <t1@test>
    conn = FakeIMAP([mail])
    calls = []
    ing = EmailIngestor(cfg, imap_factory=lambda spec: conn,
                        submitter=lambda api, cid, files: (calls.append(cid) or
                                                           {"batch_id": "b", "accepted": 4}),
                        state_dir=tmp_path)
    assert ing.poll_once()["scanned"] == 1 and calls == ["meridian_nbfc"]
    # still in the folder next cycle (FakeIMAP never removes) -> skipped
    assert ing.poll_once()["scanned"] == 0 and len(calls) == 1
    assert "default|<t1@test>" in json.loads((tmp_path / "handled_message_ids.json").read_text())
    # a fresh ingestor (restart) reloads the handled set
    ing2 = EmailIngestor(cfg, imap_factory=lambda spec: conn, state_dir=tmp_path)
    assert ing2.poll_once()["scanned"] == 0


def test_process_intake_runs_loan_engine_and_exposes_report(tmp_path, monkeypatch):
    """Default engine: the pack goes to /loan/process with the product mapped
    to a processing type and NO prompt (so the configured prompt applies);
    the intake then carries the job, the final numbers, and the report."""
    import io, urllib.request
    ing = EmailIngestor(make_config(review_mode=True),
                        imap_factory=lambda: None, state_dir=tmp_path)
    intake_id = ing.handle_message(make_mail(attachments=FULL_PACK))["intake_id"]

    import email_review
    monkeypatch.setattr(email_review, "store",
                        email_review.PendingStore(tmp_path / "pending"))
    monkeypatch.setattr(email_review, "STATE_DIR", tmp_path)
    cfg = make_config(review_mode=True, processing_api="http://engine:5055")
    monkeypatch.setattr(email_review, "_config", lambda: cfg)
    monkeypatch.setattr(email_review, "_audit",
                        lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))

    run_dir = tmp_path / "pending" / intake_id / "output" / "20260911_home"
    posted = []

    class FakeResp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def fake_urlopen(req, timeout=0):
        posted.append((req.full_url, json.loads(req.data)))
        return FakeResp(json.dumps({"job_id": "j1", "run_dir": str(run_dir),
                                    "run_folder": run_dir.name}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    # pending detail offers the engine type and the configured prompt to edit
    d = email_review.intake_detail(intake_id)
    assert d["processing_type"] == "home" and d["processing_label"] == "Home Loan"
    assert "HOME LOAN" in d["default_prompt"]

    from fastapi import HTTPException as _HE
    with pytest.raises(_HE):                                  # too short to be a prompt
        email_review.process_intake(intake_id, approver="sarah", body={"prompt": "short"})

    res = email_review.process_intake(intake_id, approver="sarah", bank_name="Demo Bank",
                                      policy_path=str(tmp_path / "no_such_policy_pack"),
                                      body={"prompt": "Reviewer prompt for this pack only, "
                                                       "check the salary slips closely."})
    assert res["engine"] == "loan" and res["job_id"] == "j1"
    assert "policy pack not found" in res["policy_note"]      # skipped, not refused
    assert posted[0][1]["policy_path"] == ""
    assert posted[0][1]["prompt"].startswith("Reviewer prompt")
    saved = email_review.store.manifest(intake_id)
    assert saved["prompt_edited"] is True and saved["prompt"].startswith("Reviewer prompt")
    assert res["processing_type"] == "home"
    url, body = posted[0]
    assert url == "http://engine:5055/loan/process"
    assert body["loan_type"] == "home" and body["prompt"].startswith("Reviewer prompt")
    assert body["input_path"].endswith("docs") and body["bank_name"] == "Demo Bank"

    # before the engine finishes: no result, report 404
    from fastapi import HTTPException
    assert email_review.intake_detail(intake_id)["result"] is None
    with pytest.raises(HTTPException):
        email_review.intake_report(intake_id, kind="html")

    # engine finishes: summary + reports land in the run folder
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(json.dumps({
        "status": "completed", "decision": "ELIGIBLE", "tokens_in": 1200,
        "tokens_out": 300, "cost_usd": 0.0021, "elapsed_s": 42.5,
        "model": "claude-haiku-4-5", "done": 4, "total": 4, "failed": 0}))
    (run_dir / "eligibility_report.html").write_text("<h1>report</h1>")
    r = email_review.intake_detail(intake_id)["result"]
    assert r["decision"] == "ELIGIBLE" and r["tokens_in"] == 1200 and r["cost_usd"] == 0.0021
    assert str(email_review.intake_report(intake_id, kind="html").path).endswith("eligibility_report.html")
    with pytest.raises(HTTPException):
        email_review.intake_report(intake_id, kind="pdf")

    events = [json.loads(l) for l in (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "intake_processed" and events[-1]["engine"] == "loan"


def test_process_intake_engine_down_is_ledgered_not_lost(tmp_path, monkeypatch):
    import urllib.error, urllib.request
    ing = EmailIngestor(make_config(review_mode=True),
                        imap_factory=lambda: None, state_dir=tmp_path)
    intake_id = ing.handle_message(make_mail(attachments=FULL_PACK))["intake_id"]
    import email_review
    monkeypatch.setattr(email_review, "store",
                        email_review.PendingStore(tmp_path / "pending"))
    monkeypatch.setattr(email_review, "_config", lambda: make_config(review_mode=True))
    monkeypatch.setattr(email_review, "_audit",
                        lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))
    def down(req, timeout=0): raise urllib.error.URLError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", down)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        email_review.process_intake(intake_id, approver="sarah")
    assert ei.value.status_code == 502 and "unreachable" in ei.value.detail
    assert email_review.store.manifest(intake_id)["status"] == "pending"   # still reviewable
    events = [json.loads(l)["event"] for l in (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert events[-1] == "process_failed"


# ── product: auto ───────────────────────────────────────────────────────
THREE_DOC_PACK = [("application.pdf", APPLICATION), ("pan.pdf", PAN_CARD),
                  ("salary.pdf", SALARY)]


def auto_config():
    return make_config(routes=[MailboxRoute(client_id="demo", senders=["*"],
                                            product="auto")])


def test_auto_product_from_subject():
    v = run(make_mail(subject="Vehicle Loan Docs", attachments=THREE_DOC_PACK), auto_config())
    assert v.ok and v.product == "vehicle_loan"
    v = run(make_mail(subject="personal Loan Docs", attachments=THREE_DOC_PACK), auto_config())
    assert v.ok and v.product == "personal_loan"
    v = run(make_mail(subject="Home Loan Docs", attachments=FULL_PACK), auto_config())
    assert v.ok and v.product == "home_loan"


def test_auto_product_subject_names_product_but_pack_incomplete():
    v = run(make_mail(subject="Home Loan Docs", attachments=THREE_DOC_PACK), auto_config())
    assert not v.ok and v.product == "home_loan"
    assert v.reason.startswith("incomplete_document_set:product=home_loan") \
        and v.missing_docs == ["property_document"]


def test_auto_product_inferred_from_documents_when_subject_silent():
    # four docs complete home_loan AND the three-doc sets; largest set wins
    v = run(make_mail(subject="Documents attached", attachments=FULL_PACK), auto_config())
    assert v.ok and v.product == "home_loan"
    # three docs complete vehicle_loan and personal_loan equally -> ambiguous
    v = run(make_mail(subject="Documents attached", attachments=THREE_DOC_PACK), auto_config())
    assert not v.ok and v.reason.startswith("product_ambiguous:personal_loan,vehicle_loan")
    # kyc form + id -> only the kyc set is complete
    kyc = fake_pdf("KYC Form", "Know Your Customer", "Date of Birth: 1-1-1990")
    v = run(make_mail(subject="docs", attachments=[("kyc.pdf", kyc), ("pan.pdf", PAN_CARD)]), auto_config())
    assert v.ok and v.product == "kyc"


def test_auto_product_nearest_miss_is_reported():
    v = run(make_mail(subject="docs", attachments=[("application.pdf", APPLICATION),
                                                     ("pan.pdf", PAN_CARD)]), auto_config())
    assert not v.ok and v.product in ("vehicle_loan", "personal_loan") \
        and v.missing_docs == ["income_proof"]


def test_auto_route_still_scoped_and_explicit_routes_unchanged():
    cfg = make_config(routes=[
        MailboxRoute(client_id="acme", senders=["*@acme.test"], product="kyc"),
        MailboxRoute(client_id="demo", senders=["*"], product="auto")])
    v = run(make_mail(sender="x@acme.test", subject="Vehicle Loan Docs",
                      attachments=THREE_DOC_PACK), cfg)
    assert not v.ok and v.product == "kyc"        # first matching route, explicit product
    v = run(make_mail(sender="x@other.test", subject="Vehicle Loan Docs",
                      attachments=THREE_DOC_PACK), cfg)
    assert v.ok and v.product == "vehicle_loan"


def test_process_intake_without_prompt_records_the_configured_one(tmp_path, monkeypatch):
    import io, urllib.request, email_review, loan_processing as lp
    ing = EmailIngestor(make_config(review_mode=True), imap_factory=lambda: None, state_dir=tmp_path)
    intake_id = ing.handle_message(make_mail(attachments=FULL_PACK))["intake_id"]
    monkeypatch.setattr(email_review, "store", email_review.PendingStore(tmp_path / "pending"))
    monkeypatch.setattr(email_review, "_config", lambda: make_config(review_mode=True))
    monkeypatch.setattr(email_review, "_audit", lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))
    monkeypatch.setattr(lp, "PROMPTS_PATH", tmp_path / "prompts.json")
    lp.save_prompt_overrides({"home": "Bank-configured home loan prompt, twenty+ chars."}, "ops")

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    sent = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: (
        sent.append(json.loads(req.data)) or R(json.dumps({"job_id": "j2", "run_dir": str(tmp_path / "r")}).encode())))
    email_review.process_intake(intake_id, approver="sarah")
    assert sent[0]["prompt"] == ""                           # engine applies its configured prompt
    m = email_review.store.manifest(intake_id)
    assert m["prompt_edited"] is False and m["prompt"].startswith("Bank-configured")
    last = json.loads((tmp_path / "email_audit.jsonl").read_text().splitlines()[-1])
    assert last["prompt_edited"] is False and len(last["prompt_sha256"]) == 64


def test_processed_intake_can_be_run_again_and_keeps_history(tmp_path, monkeypatch):
    import io, urllib.request, email_review
    ing = EmailIngestor(make_config(review_mode=True), imap_factory=lambda: None, state_dir=tmp_path)
    intake_id = ing.handle_message(make_mail(attachments=FULL_PACK))["intake_id"]
    monkeypatch.setattr(email_review, "store", email_review.PendingStore(tmp_path / "pending"))
    monkeypatch.setattr(email_review, "_config", lambda: make_config(review_mode=True))
    monkeypatch.setattr(email_review, "_audit", lambda: EmailAuditLog(tmp_path / "email_audit.jsonl"))

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    calls = {"n": 0}
    def fake_urlopen(req, timeout=0):
        url = req if isinstance(req, str) else req.full_url
        if url.endswith("/loan/process"):
            calls["n"] += 1
            return R(json.dumps({"job_id": f"j{calls['n']}", "run_dir": str(tmp_path / f"r{calls['n']}")}).encode())
        # /loan/jobs/<id>: j1 finished, j2 still running
        jid = url.rsplit("/", 1)[-1]
        return R(json.dumps({"status": "running" if jid == "j2" else "completed"}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    from fastapi import HTTPException

    email_review.process_intake(intake_id, approver="sarah")
    with pytest.raises(HTTPException):                       # plain process: already processed
        email_review.process_intake(intake_id, approver="sarah")
    (tmp_path / "r1").mkdir(); (tmp_path / "r1" / "summary.json").write_text(json.dumps({"status": "completed", "decision": "NOT_ELIGIBLE"}))

    res = email_review.process_intake(intake_id, approver="sarah", rerun=True,
                                      body={"prompt": "Second look: focus on the income proof pages."})
    assert res["job_id"] == "j2"
    m = email_review.store.manifest(intake_id)
    assert m["status"] == "processed" and m["job_id"] == "j2" and m["prompt_edited"] is True
    assert len(m["runs"]) == 1 and m["runs"][0]["job_id"] == "j1"
    assert m["runs"][0]["result"]["decision"] == "NOT_ELIGIBLE"

    with pytest.raises(HTTPException) as ei:                 # j2 still running -> refuse
        email_review.process_intake(intake_id, approver="sarah", rerun=True)
    assert "still in progress" in ei.value.detail
    d = email_review.intake_detail(intake_id)
    assert d["run_active"] is True and d["default_prompt"]
    events = [json.loads(l)["event"] for l in (tmp_path / "email_audit.jsonl").read_text().splitlines()]
    assert "intake_rerun_requested" in events
