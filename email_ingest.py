# Part of the PrefectOS core package — email ingestion connector.
"""Governed email → batch-ingest connector, with layered validation.

Validation stages per email:
  1. Sender — allowlist route (client + product), address syntax, and
     SPF/DKIM/DMARC via Authentication-Results (anti-spoofing).
  2. Attachments — extension, size, non-empty, SHA-256 dedup, PDF
     structure, template classification (email_validation.py).
  3. Document set — the pack must be complete for the route's product;
     incomplete packs are rejected with the exact missing list.

With review_mode (default) accepted packs are PARKED for human review
(email_review.PendingStore): the operator reads the email body,
downloads documents, and clicks "Process documents", which routes the
pack to the queue for its product. review_mode=false auto-submits to
the batch API instead. Every decision is sealed into a hash-chained
JSONL audit log.

Secrets: mailbox password ONLY from EMAIL_INGEST_PASSWORD env var.

Usage:
    python email_ingest.py --once | --poll 120 | --dry-run | --verify-audit
"""
from __future__ import annotations

import argparse
import email
import email.policy
import hashlib
import imaplib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from email_validation import (
    DocumentValidator,
    validate_sender_authenticity,
)

# ── Defaults ───────────────────────────────────────────────────────────
CONFIG_PATH = Path(os.getenv("EMAIL_INGEST_CONFIG", "email_ingest_config.json"))
STATE_DIR = Path(os.getenv("EMAIL_INGEST_STATE", "project_output/email_ingest"))
ALLOWED_EXTENSIONS = {".pdf"}
MAX_ATTACHMENT_MB = 25
MAX_DOCS_PER_MAIL = 100                # mirrors MAX_BATCH in batch_ingest.api


# ── Config ─────────────────────────────────────────────────────────────
@dataclass
class MailboxRoute:
    """Maps allowed sender addresses to a client workspace + product."""
    client_id: str
    senders: list[str]                 # exact addresses or *@domain patterns
    product: str | None = None         # keys into doc_templates document_sets

    def matches(self, addr: str) -> bool:
        addr = addr.lower().strip()
        for pat in self.senders:
            pat = pat.lower().strip()
            if pat.startswith("*@"):
                if addr.endswith(pat[1:]):
                    return True
            elif addr == pat:
                return True
        return False


@dataclass
class EmailIngestConfig:
    imap_host: str
    imap_user: str
    mailbox: str = "INBOX"
    imap_port: int = 993
    ingest_api: str = "http://127.0.0.1:8000/ingest/batches"
    processed_label: str = "PrefectOS/Processed"
    rejected_label: str = "PrefectOS/Rejected"
    routes: list[MailboxRoute] = field(default_factory=list)
    allowed_extensions: set[str] = field(default_factory=lambda: set(ALLOWED_EXTENSIONS))
    max_attachment_mb: int = MAX_ATTACHMENT_MB
    require_authentication: bool = True        # SPF/DKIM/DMARC must pass
    templates_file: str = "doc_templates.json" # "" disables template checks
    enforce_document_set: bool = True          # reject incomplete packs
    review_mode: bool = True                   # park for human review vs auto-submit
    queues: dict = field(default_factory=dict) # product -> {"api": url} overrides

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "EmailIngestConfig":
        raw = json.loads(Path(path).read_text())
        routes = [MailboxRoute(**r) for r in raw.pop("routes", [])]
        exts = {e.lower() if e.startswith(".") else f".{e.lower()}"
                for e in raw.pop("allowed_extensions", list(ALLOWED_EXTENSIONS))}
        return cls(routes=routes, allowed_extensions=exts, **raw)

    def route_for(self, addr: str) -> MailboxRoute | None:
        for r in self.routes:
            if r.matches(addr):
                return r
        return None

    def load_validator(self) -> DocumentValidator | None:
        if not self.templates_file:
            return None
        p = Path(self.templates_file)
        return DocumentValidator.load(p) if p.exists() else None


# ── Hash-chained audit log ─────────────────────────────────────────────
class EmailAuditLog:
    """Append-only JSONL where each record carries the SHA-256 of the
    previous record, so tampering or deletion is detectable."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = self._last_hash()

    def _last_hash(self) -> str:
        if not self.path.exists():
            return "GENESIS"
        last = ""
        with self.path.open() as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return "GENESIS"
        return json.loads(last)["record_hash"]

    def record(self, event: str, **fields) -> dict:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
            "prev_hash": self._prev,
        }
        rec["record_hash"] = hashlib.sha256(
            json.dumps(rec, sort_keys=True).encode()
        ).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        self._prev = rec["record_hash"]
        return rec

    def verify(self) -> tuple[bool, str]:
        prev = "GENESIS"
        with self.path.open() as f:
            for n, line in enumerate(f, 1):
                if not line.strip():
                    continue
                rec = json.loads(line)
                claimed = rec.pop("record_hash")
                if rec.get("prev_hash") != prev:
                    return False, f"chain break at line {n}"
                actual = hashlib.sha256(
                    json.dumps(rec, sort_keys=True).encode()
                ).hexdigest()
                if actual != claimed:
                    return False, f"hash mismatch at line {n}"
                prev = claimed
        return True, "ok"


# ── Validation ─────────────────────────────────────────────────────────
@dataclass
class Verdict:
    ok: bool
    reason: str
    client_id: str | None = None
    product: str | None = None
    attachments: list[tuple[str, bytes]] = field(default_factory=list)
    doc_types: dict[str, str | None] = field(default_factory=dict)
    missing_docs: list[str] = field(default_factory=list)


_ADDR_RE = re.compile(r"<([^>]+)>")


def sender_address(msg: EmailMessage) -> str:
    raw = msg.get("From", "") or ""
    m = _ADDR_RE.search(raw)
    return (m.group(1) if m else raw).lower().strip()


def validate_message(msg: EmailMessage, cfg: EmailIngestConfig,
                     seen_hashes: set[str],
                     validator: DocumentValidator | None = None) -> Verdict:
    """Pure decision function: what (if anything) may enter the pipeline."""
    addr = sender_address(msg)
    if not addr:
        return Verdict(False, "no_sender")

    # Stage 1a: allowlist route
    route = cfg.route_for(addr)
    if route is None:
        return Verdict(False, "sender_not_allowlisted")

    # Stage 1b: address syntax + SPF/DKIM/DMARC authenticity
    ok, why = validate_sender_authenticity(
        msg, addr, require_auth=cfg.require_authentication)
    if not ok:
        return Verdict(False, why, client_id=route.client_id,
                       product=route.product)

    # Stage 2a: basic attachment checks
    attachments: list[tuple[str, bytes]] = []
    rejected: list[str] = []
    limit = cfg.max_attachment_mb * 1024 * 1024

    for part in msg.iter_attachments():
        name = Path(part.get_filename() or "unnamed").name  # strip any path
        ext = Path(name).suffix.lower()
        payload = part.get_payload(decode=True) or b""
        if ext not in cfg.allowed_extensions:
            rejected.append(f"{name}:bad_type")
            continue
        if len(payload) == 0:
            rejected.append(f"{name}:empty")
            continue
        if len(payload) > limit:
            rejected.append(f"{name}:too_large")
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_hashes:
            rejected.append(f"{name}:duplicate")
            continue
        attachments.append((name, payload))

    if not attachments:
        reason = "no_valid_attachments" if not rejected else \
                 "all_attachments_rejected:" + ",".join(rejected)
        return Verdict(False, reason, client_id=route.client_id,
                       product=route.product)

    if len(attachments) > MAX_DOCS_PER_MAIL:
        return Verdict(False, "too_many_documents",
                       client_id=route.client_id, product=route.product)

    # Stage 2b: template classification of each attachment
    doc_types: dict[str, str | None] = {}
    if validator is not None:
        kept: list[tuple[str, bytes]] = []
        for name, payload in attachments:
            cls = validator.classify(name, payload)
            doc_types[name] = cls.doc_type
            if cls.doc_type is None:
                rejected.append(f"{name}:{cls.detail}")
            else:
                kept.append((name, payload))
        attachments = kept
        if not attachments:
            return Verdict(False,
                           "all_attachments_rejected:" + ",".join(rejected),
                           client_id=route.client_id, product=route.product,
                           doc_types=doc_types)

        # Stage 3: document-set completeness for the route's product
        if cfg.enforce_document_set and route.product:
            classified = [type("C", (), {"doc_type": doc_types[n]})()
                          for n, _ in attachments]
            complete, missing = validator.check_set(route.product, classified)
            if not complete:
                return Verdict(False,
                               "incomplete_document_set:missing="
                               + ",".join(missing),
                               client_id=route.client_id,
                               product=route.product,
                               doc_types=doc_types, missing_docs=missing)

    reason = "accepted" if not rejected else \
             "partial_accept:" + ",".join(rejected)
    return Verdict(True, reason, client_id=route.client_id,
                   product=route.product, attachments=attachments,
                   doc_types=doc_types)


# ── Submission to the batch-ingest API ─────────────────────────────────
def submit_to_ingest(api_url: str, client_id: str,
                     files: list[tuple[str, bytes]]) -> dict:
    """multipart/form-data POST to /ingest/batches?user_id=<client_id>."""
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, payload in files:
        body += (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="files"; filename="{name}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode()
        body += payload + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{api_url}?user_id={urllib.parse.quote(client_id)}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


# ── The connector ──────────────────────────────────────────────────────
class EmailIngestor:
    def __init__(self, cfg: EmailIngestConfig,
                 imap_factory=None, submitter=submit_to_ingest,
                 state_dir: Path = STATE_DIR):
        self.cfg = cfg
        self.imap_factory = imap_factory or self._default_imap
        self.submitter = submitter
        self.validator = cfg.load_validator()
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit = EmailAuditLog(self.state_dir / "email_audit.jsonl")
        self.seen_path = self.state_dir / "seen_hashes.json"
        self.seen: set[str] = set(
            json.loads(self.seen_path.read_text())
        ) if self.seen_path.exists() else set()

    # -- IMAP plumbing --------------------------------------------------
    def _default_imap(self):
        password = os.environ.get("EMAIL_INGEST_PASSWORD")
        if not password:
            raise RuntimeError(
                "EMAIL_INGEST_PASSWORD not set — refusing to start. "
                "Export it in the environment / systemd EnvironmentFile."
            )
        conn = imaplib.IMAP4_SSL(self.cfg.imap_host, self.cfg.imap_port)
        conn.login(self.cfg.imap_user, password)
        return conn

    def _move(self, conn, msg_id: bytes, label: str):
        with_label = label.encode() if isinstance(label, str) else label
        try:
            conn.create(with_label)
        except Exception:
            pass
        try:
            conn.copy(msg_id, with_label)
            conn.store(msg_id, "+FLAGS", "\\Deleted")
        except Exception:
            conn.store(msg_id, "+FLAGS", "\\Seen")   # never lose mail

    # -- Core cycle -----------------------------------------------------
    def poll_once(self, dry_run: bool = False) -> dict:
        stats = {"scanned": 0, "accepted": 0, "rejected": 0, "submitted_batches": []}
        conn = self.imap_factory()
        try:
            conn.select(self.cfg.mailbox)
            _, data = conn.search(None, "UNSEEN")
            ids = data[0].split() if data and data[0] else []
            for msg_id in ids:
                _, msg_data = conn.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                stats["scanned"] += 1
                outcome = self.handle_message(msg, dry_run=dry_run)
                if outcome["accepted"]:
                    stats["accepted"] += 1
                    if outcome.get("batch_id"):
                        stats["submitted_batches"].append(outcome["batch_id"])
                    if not dry_run:
                        self._move(conn, msg_id, self.cfg.processed_label)
                else:
                    stats["rejected"] += 1
                    if not dry_run:
                        self._move(conn, msg_id, self.cfg.rejected_label)
            if not dry_run:
                conn.expunge()
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return stats

    def handle_message(self, msg: EmailMessage, dry_run: bool = False) -> dict:
        addr = sender_address(msg)
        subject = str(msg.get("Subject", ""))[:200]
        message_id = str(msg.get("Message-ID", ""))[:200]
        verdict = validate_message(msg, self.cfg, self.seen, self.validator)

        base = {
            "sender": addr, "subject": subject, "message_id": message_id,
            "client_id": verdict.client_id, "product": verdict.product,
            "reason": verdict.reason,
        }
        if verdict.doc_types:
            base["doc_types"] = verdict.doc_types
        if verdict.missing_docs:
            base["missing_docs"] = verdict.missing_docs

        if not verdict.ok:
            self.audit.record("email_rejected", **base)
            return {"accepted": False, **base}

        doc_hashes = [hashlib.sha256(p).hexdigest() for _, p in verdict.attachments]
        self.audit.record(
            "email_accepted", **base,
            n_docs=len(verdict.attachments),
            doc_names=[n for n, _ in verdict.attachments],
            doc_sha256=doc_hashes,
        )

        if dry_run:
            return {"accepted": True, "batch_id": None, **base}

        if self.cfg.review_mode:
            # Park for human review: body + docs stored; operator clicks
            # "Process documents" in the UI (email_review.process_intake),
            # which routes to the queue for this product.
            from email_review import PendingStore
            body = ""
            try:
                part = msg.get_body(preferencelist=("plain", "html"))
                if part is not None:
                    body = str(part.get_content())
            except Exception:
                pass
            intake_id = PendingStore(self.state_dir / "pending").park(
                sender=addr, subject=subject, message_id=message_id,
                client_id=verdict.client_id, product=verdict.product,
                body_text=body, attachments=verdict.attachments,
                doc_types=verdict.doc_types,
            )
            self.seen.update(doc_hashes)
            self.seen_path.write_text(json.dumps(sorted(self.seen)))
            self.audit.record("email_pending_review", **base,
                              intake_id=intake_id,
                              n_docs=len(verdict.attachments))
            return {"accepted": True, "batch_id": None,
                    "intake_id": intake_id, **base}

        try:
            result = self.submitter(self.cfg.ingest_api, verdict.client_id,
                                    verdict.attachments)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            self.audit.record("submit_failed", **base, error=str(exc)[:300])
            return {"accepted": False, **base, "reason": "submit_failed"}

        self.seen.update(doc_hashes)
        self.seen_path.write_text(json.dumps(sorted(self.seen)))
        self.audit.record("batch_submitted", **base,
                          batch_id=result.get("batch_id"),
                          n_docs=result.get("accepted"))
        return {"accepted": True, "batch_id": result.get("batch_id"), **base}


# ── CLI ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="PrefectOS email ingestion connector")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--once", action="store_true", help="single poll cycle")
    ap.add_argument("--poll", type=int, metavar="SECONDS",
                    help="daemon mode: poll every N seconds")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate and audit only; submit nothing, move nothing")
    ap.add_argument("--verify-audit", action="store_true",
                    help="verify the email audit hash chain and exit")
    args = ap.parse_args()

    if args.verify_audit:
        log = EmailAuditLog(STATE_DIR / "email_audit.jsonl")
        ok, detail = log.verify()
        print(f"audit chain: {'VALID' if ok else 'BROKEN'} ({detail})")
        raise SystemExit(0 if ok else 1)

    cfg = EmailIngestConfig.load(Path(args.config))
    ing = EmailIngestor(cfg)

    if args.poll:
        print(f"[email_ingest] polling {cfg.imap_user}@{cfg.imap_host} "
              f"every {args.poll}s")
        while True:
            stats = ing.poll_once(dry_run=args.dry_run)
            print(f"[email_ingest] {datetime.now().isoformat(timespec='seconds')} "
                  f"{stats}")
            time.sleep(args.poll)
    else:
        print(ing.poll_once(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
