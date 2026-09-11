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

Mailboxes: the top-level imap_* fields describe the built-in "default"
intake mailbox. Additional dedicated mailboxes (one per client, living in
the client's own tenant) go in "mailboxes": [{id, imap_host, imap_user,
folder, auth, secret_env, ...}] and routes bind to one with
"mailbox": "<id>". Every poll cycle visits each mailbox that has at
least one route bound to it; a mailbox that fails (expired token, host
down) is ledgered and skipped so it never stalls the others.

Auth per mailbox:
  password        IMAP LOGIN; secret from the env var named in secret_env
  oauth_microsoft Entra client-credentials -> XOAUTH2 (tenant_id,
                  oauth_client_id, client secret in secret_env)
  oauth_google    service-account JSON path in secret_env, domain-wide
                  delegation to imap_user -> XOAUTH2 (needs google-auth)

Secrets: NEVER in config — only in the env var each mailbox names
(default mailbox: EMAIL_INGEST_PASSWORD).

Usage:
    python email_ingest.py --once | --poll 120 | --dry-run | --verify-audit
"""
from __future__ import annotations

import argparse
import email
import email.policy
import base64
import hashlib
import imaplib
import inspect
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

# Secrets come from the environment; on a laptop that usually means .env.
# Best-effort: systemd EnvironmentFile deployments need no python-dotenv.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

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
DEFAULT_MAILBOX_ID = "default"
AUTH_METHODS = ("password", "oauth_microsoft", "oauth_google")
PROVIDERS = ("generic", "google", "microsoft")


@dataclass
class MailboxSpec:
    """One IMAP mailbox the connector polls. Carries connection details
    and the NAME of the env var holding its secret — never the secret."""
    id: str
    imap_host: str
    imap_user: str
    imap_port: int = 993
    folder: str = "INBOX"
    label: str = ""
    provider: str = "generic"          # generic | google | microsoft
    auth: str = "password"             # see AUTH_METHODS
    secret_env: str = "EMAIL_INGEST_PASSWORD"
    tenant_id: str = ""                # oauth_microsoft
    oauth_client_id: str = ""          # oauth_microsoft app (client) id

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", self.id or ""):
            raise ValueError(f"mailbox id {self.id!r} must be [A-Za-z0-9_-]")
        if self.auth not in AUTH_METHODS:
            raise ValueError(f"mailbox {self.id!r}: unknown auth {self.auth!r}")
        if self.provider not in PROVIDERS:
            raise ValueError(f"mailbox {self.id!r}: unknown provider {self.provider!r}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.secret_env or ""):
            raise ValueError(f"mailbox {self.id!r}: secret_env must be an env var name")
        if self.auth == "oauth_microsoft" and not (self.tenant_id and self.oauth_client_id):
            raise ValueError(f"mailbox {self.id!r}: oauth_microsoft needs tenant_id and oauth_client_id")

    @property
    def key(self) -> str:
        return f"{self.imap_user}@{self.imap_host}/{self.folder}"

    def public(self) -> dict:
        """Config view safe for the UI / audit log (contains no secret)."""
        d = self.__dict__.copy()
        d["key"] = self.key
        d["secret_present"] = bool(os.environ.get(self.secret_env))
        return d


@dataclass
class MailboxRoute:
    """Maps allowed sender addresses to a client workspace + product."""
    client_id: str
    senders: list[str]                 # exact addresses, *@domain, or "*"
    product: str | None = None         # keys into doc_templates document_sets
    mailbox: str = DEFAULT_MAILBOX_ID  # id of the mailbox this route reads

    def matches(self, addr: str) -> bool:
        addr = addr.lower().strip()
        for pat in self.senders:
            pat = pat.lower().strip()
            if pat == "*":              # dedicated client mailbox: any sender
                return True
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
    # Where "Process documents" sends an approved pack:
    #   loan  -> the loan/account processing engine (server.py /loan/process):
    #            per-type prompt from Settings, eligibility report, tokens/cost
    #   batch -> the batch-ingest queue (ingest_api / queues), the old path
    processing_engine: str = "loan"
    processing_api: str = "http://127.0.0.1:5055"
    # Default-mailbox auth (the top-level imap_* fields ARE the default mailbox)
    provider: str = "generic"
    auth: str = "password"
    secret_env: str = "EMAIL_INGEST_PASSWORD"
    tenant_id: str = ""
    oauth_client_id: str = ""
    # Dedicated per-client mailboxes; routes bind with mailbox=<id>
    mailboxes: list[MailboxSpec] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "EmailIngestConfig":
        raw = dict(raw)
        routes = [MailboxRoute(**r) for r in raw.pop("routes", [])]
        boxes = [MailboxSpec(**m) for m in raw.pop("mailboxes", [])]
        exts = {e.lower() if e.startswith(".") else f".{e.lower()}"
                for e in raw.pop("allowed_extensions", list(ALLOWED_EXTENSIONS))}
        cfg = cls(routes=routes, mailboxes=boxes, allowed_extensions=exts, **raw)
        cfg.validate_bindings()
        return cfg

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "EmailIngestConfig":
        return cls.from_dict(json.loads(Path(path).read_text()))

    def validate_bindings(self) -> None:
        ids = [m.id for m in self.mailboxes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate mailbox ids: {sorted(dupes)}")
        if DEFAULT_MAILBOX_ID in ids:
            raise ValueError(f"mailbox id {DEFAULT_MAILBOX_ID!r} is reserved")
        known = set(ids) | {DEFAULT_MAILBOX_ID}
        for r in self.routes:
            if r.mailbox not in known:
                raise ValueError(
                    f"route {r.client_id!r} binds unknown mailbox {r.mailbox!r}")

    def default_mailbox(self) -> MailboxSpec:
        return MailboxSpec(
            id=DEFAULT_MAILBOX_ID, label="Default intake mailbox",
            imap_host=self.imap_host, imap_user=self.imap_user,
            imap_port=self.imap_port, folder=self.mailbox,
            provider=self.provider, auth=self.auth, secret_env=self.secret_env,
            tenant_id=self.tenant_id, oauth_client_id=self.oauth_client_id,
        )

    def all_mailboxes(self) -> list[MailboxSpec]:
        return [self.default_mailbox(), *self.mailboxes]

    def mailbox_by_id(self, mailbox_id: str) -> MailboxSpec | None:
        for m in self.all_mailboxes():
            if m.id == mailbox_id:
                return m
        return None

    def routes_for_mailbox(self, mailbox_id: str) -> list[MailboxRoute]:
        return [r for r in self.routes if r.mailbox == mailbox_id]

    def polled_mailboxes(self) -> list[MailboxSpec]:
        """Mailboxes worth visiting: every dedicated one with a route bound,
        plus the default whenever a route uses it (or no routes exist yet,
        so an empty config still exercises the login path)."""
        out = []
        for m in self.all_mailboxes():
            bound = self.routes_for_mailbox(m.id)
            if bound or (m.id == DEFAULT_MAILBOX_ID and not self.routes):
                out.append(m)
        return out

    def route_for(self, addr: str,
                  mailbox_id: str | None = None) -> MailboxRoute | None:
        """First route whose allowlist matches; when a mailbox is given only
        routes bound to that mailbox are considered, so a sender allowed
        into client A's box is not thereby allowed into client B's."""
        for r in self.routes:
            if mailbox_id is not None and r.mailbox != mailbox_id:
                continue
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


AUTO_PRODUCT = "auto"

# Words in a subject line that name a product. Checked longest-first so
# "loan against property" is not read as a personal loan by accident.
PRODUCT_SUBJECT_HINTS: dict[str, tuple[str, ...]] = {
    "mortgage": ("loan against property", "mortgage", "lap "),
    "home_loan": ("home loan", "housing loan", "home"),
    "vehicle_loan": ("vehicle loan", "vehicle", "car loan", "auto loan",
                     "two wheeler", "two-wheeler", "car"),
    "personal_loan": ("personal loan", "personal"),
    "kyc": ("kyc", "know your customer"),
    "statement": ("statement",),
}


def product_from_subject(subject: str, known: set[str]) -> str | None:
    low = f" {(subject or '').lower()} "
    best: tuple[int, str] | None = None
    for product, hints in PRODUCT_SUBJECT_HINTS.items():
        if product not in known:
            continue
        for h in hints:
            if h in low and (best is None or len(h) > best[0]):
                best = (len(h), product)
    return best[1] if best else None


def detect_product(subject: str, doc_types: dict[str, str | None],
                   validator: DocumentValidator) -> tuple[str | None, str, list[str]]:
    """Work out which product a pack is for when the route says "auto".

    Returns (product, reason, missing). The subject decides when it names a
    product; otherwise the pack is matched against every document set and
    the unique complete one wins (largest set on a tie, so a home-loan pack
    is not mistaken for a personal-loan pack that it also satisfies).
    """
    sets = validator.document_sets or {}
    classified = [type("C", (), {"doc_type": t})() for t in doc_types.values()]
    hinted = product_from_subject(subject, set(sets))
    if hinted:
        complete, missing = validator.check_set(hinted, classified)
        return (hinted, "subject", []) if complete else (hinted, "subject", missing)
    complete_sets = [(len(req), prod) for prod, req in sets.items()
                     if validator.check_set(prod, classified)[0]]
    if not complete_sets:
        # nearest miss: the product with the fewest missing documents
        nearest = min(sets, key=lambda prod: len(validator.check_set(prod, classified)[1]))
        return nearest, "nearest", validator.check_set(nearest, classified)[1]
    complete_sets.sort(reverse=True)
    if len(complete_sets) > 1 and complete_sets[0][0] == complete_sets[1][0]:
        tied = sorted(prod for n, prod in complete_sets if n == complete_sets[0][0])
        return None, "ambiguous:" + ",".join(tied), []
    return complete_sets[0][1], "documents", []


def validate_message(msg: EmailMessage, cfg: EmailIngestConfig,
                     seen_hashes: set[str],
                     validator: DocumentValidator | None = None,
                     mailbox_id: str | None = None) -> Verdict:
    """Pure decision function: what (if anything) may enter the pipeline.
    mailbox_id restricts the allowlist to routes bound to that mailbox."""
    addr = sender_address(msg)
    if not addr:
        return Verdict(False, "no_sender")

    # Stage 1a: allowlist route (scoped to the mailbox the mail arrived in)
    route = cfg.route_for(addr, mailbox_id)
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
    product = route.product
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

        # Stage 3: document-set completeness for the route's product.
        # A route may say "auto": the product is then read from the subject
        # line or inferred from which document set the pack completes.
        product = route.product
        if product == AUTO_PRODUCT:
            kept_types = {n: doc_types[n] for n, _ in attachments}
            product, how, missing = detect_product(
                str(msg.get("Subject", "")), kept_types, validator)
            if product is None:
                return Verdict(False, "product_" + how
                               + ":name_the_product_in_the_subject",
                               client_id=route.client_id, doc_types=doc_types)
            if missing and cfg.enforce_document_set:
                return Verdict(False,
                               f"incomplete_document_set:product={product}:missing="
                               + ",".join(missing),
                               client_id=route.client_id, product=product,
                               doc_types=doc_types, missing_docs=missing)
        if cfg.enforce_document_set and product:
            classified = [type("C", (), {"doc_type": doc_types[n]})()
                          for n, _ in attachments]
            complete, missing = validator.check_set(product, classified)
            if not complete:
                return Verdict(False,
                               "incomplete_document_set:missing="
                               + ",".join(missing),
                               client_id=route.client_id,
                               product=product,
                               doc_types=doc_types, missing_docs=missing)

    reason = "accepted" if not rejected else \
             "partial_accept:" + ",".join(rejected)
    resolved = route.product
    if resolved == AUTO_PRODUCT:
        # validator absent or set checks off: still resolve from the subject
        resolved = (product if validator is not None else None) or \
            product_from_subject(str(msg.get("Subject", "")),
                                 set(PRODUCT_SUBJECT_HINTS))
    return Verdict(True, reason, client_id=route.client_id,
                   product=resolved, attachments=attachments,
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


# ── Mailbox authentication ─────────────────────────────────────────────
class MailboxAuthError(RuntimeError):
    """Credential missing/invalid for one mailbox. Never carries the secret."""


_TOKEN_CACHE: dict[str, tuple[str, float]] = {}   # mailbox key -> (token, expiry)


def _secret_for(spec: MailboxSpec) -> str:
    value = os.environ.get(spec.secret_env)
    if not value:
        raise MailboxAuthError(
            f"mailbox {spec.id!r}: env var {spec.secret_env} not set — "
            "export it in the environment / systemd EnvironmentFile.")
    return value


def _oauth_microsoft_token(spec: MailboxSpec) -> str:
    """Entra ID client-credentials grant scoped to Exchange Online IMAP.
    Requires the app to hold IMAP.AccessAsApp and a service principal
    granted FullAccess on exactly this mailbox."""
    key = f"ms:{spec.key}"
    tok, exp = _TOKEN_CACHE.get(key, ("", 0.0))
    if tok and exp - time.time() > 120:
        return tok
    body = urllib.parse.urlencode({
        "client_id": spec.oauth_client_id,
        "client_secret": _secret_for(spec),
        "scope": "https://outlook.office365.com/.default",
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request(
        f"https://login.microsoftonline.com/{spec.tenant_id}/oauth2/v2.0/token",
        data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise MailboxAuthError(
            f"mailbox {spec.id!r}: Microsoft token request failed "
            f"({e.code}): {detail}") from None
    tok = data["access_token"]
    _TOKEN_CACHE[key] = (tok, time.time() + int(data.get("expires_in", 3600)))
    return tok


def _oauth_google_token(spec: MailboxSpec) -> str:
    """Service account with domain-wide delegation, impersonating imap_user.
    secret_env names the env var holding the PATH to the service-account
    JSON key. Signing the JWT needs google-auth (optional dependency)."""
    key = f"g:{spec.key}"
    tok, exp = _TOKEN_CACHE.get(key, ("", 0.0))
    if tok and exp - time.time() > 120:
        return tok
    key_path = _secret_for(spec)
    try:
        from google.oauth2 import service_account          # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
    except ImportError:
        raise MailboxAuthError(
            f"mailbox {spec.id!r}: oauth_google needs `pip install google-auth`")
    if not Path(key_path).exists():
        raise MailboxAuthError(
            f"mailbox {spec.id!r}: service-account key file not found "
            f"(env {spec.secret_env})")
    creds = service_account.Credentials.from_service_account_file(
        key_path, scopes=["https://mail.google.com/"]).with_subject(spec.imap_user)
    creds.refresh(Request())
    expiry = creds.expiry.timestamp() if creds.expiry else time.time() + 3000
    _TOKEN_CACHE[key] = (creds.token, expiry)
    return creds.token


def _xoauth2(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def open_mailbox(spec: MailboxSpec):
    """Connect + authenticate one mailbox. Returns a logged-in IMAP4_SSL."""
    # Resolve credentials before touching the network: a missing env var
    # is reported instantly and never as a connection error.
    if spec.auth == "password":
        password, token = _secret_for(spec), ""
    else:
        password = ""
        token = (_oauth_microsoft_token(spec) if spec.auth == "oauth_microsoft"
                 else _oauth_google_token(spec))
    conn = imaplib.IMAP4_SSL(spec.imap_host, spec.imap_port)
    try:
        if spec.auth == "password":
            conn.login(spec.imap_user, password)
        else:
            conn.authenticate("XOAUTH2", lambda _: _xoauth2(spec.imap_user, token))
    except imaplib.IMAP4.error as e:
        try:
            conn.logout()
        except Exception:
            pass
        raise MailboxAuthError(
            f"mailbox {spec.id!r}: IMAP authentication refused "
            f"({str(e)[:160]})") from None
    except Exception:
        try:
            conn.logout()
        except Exception:
            pass
        raise
    return conn


def test_connection(spec: MailboxSpec) -> dict:
    """Login, select the folder, count unseen mail, log out. Used by the
    Settings UI "Test connection" button. Moves nothing."""
    started = time.time()
    try:
        conn = open_mailbox(spec)
    except (MailboxAuthError, OSError, imaplib.IMAP4.error) as e:
        return {"ok": False, "mailbox": spec.id, "error": str(e)[:300]}
    try:
        typ, _ = conn.select(spec.folder, readonly=True)
        if typ != "OK":
            return {"ok": False, "mailbox": spec.id,
                    "error": f"folder {spec.folder!r} not selectable"}
        _, data = conn.search(None, "UNSEEN")
        unseen = len(data[0].split()) if data and data[0] else 0
        return {"ok": True, "mailbox": spec.id, "folder": spec.folder,
                "unseen": unseen, "ms": round((time.time() - started) * 1000)}
    except (OSError, imaplib.IMAP4.error) as e:
        return {"ok": False, "mailbox": spec.id, "error": str(e)[:300]}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


# ── The connector ──────────────────────────────────────────────────────
class EmailIngestor:
    def __init__(self, cfg: EmailIngestConfig,
                 imap_factory=None, submitter=submit_to_ingest,
                 state_dir: Path = STATE_DIR):
        self.cfg = cfg
        # imap_factory(spec) -> logged-in connection. A zero-arg factory
        # (legacy / tests) is accepted and used for every mailbox.
        self.imap_factory = imap_factory or open_mailbox
        self.submitter = submitter
        self.validator = cfg.load_validator()
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit = EmailAuditLog(self.state_dir / "email_audit.jsonl")
        self.seen_path = self.state_dir / "seen_hashes.json"
        self.seen: set[str] = set(
            json.loads(self.seen_path.read_text())
        ) if self.seen_path.exists() else set()
        self.status_path = self.state_dir / "mailbox_status.json"
        # Message-IDs already handled. The folder is scanned in full (not just
        # UNSEEN) so a person opening a mail in the webmail client cannot hide
        # it from intake; this set is what stops a message being handled twice
        # if it is still in the folder (e.g. a failed move, or a dry-run).
        self.handled_path = self.state_dir / "handled_message_ids.json"
        self.handled: set[str] = set(
            json.loads(self.handled_path.read_text())
        ) if self.handled_path.exists() else set()

    # -- IMAP plumbing --------------------------------------------------
    def _open(self, spec: MailboxSpec):
        try:
            takes_spec = len(inspect.signature(self.imap_factory).parameters) >= 1
        except (TypeError, ValueError):
            takes_spec = True
        return self.imap_factory(spec) if takes_spec else self.imap_factory()

    def _write_status(self, mailbox_id: str, **fields):
        """Per-mailbox health for the Settings page: last poll, last
        success, last error, counts. Best-effort, never raises."""
        try:
            status = (json.loads(self.status_path.read_text())
                      if self.status_path.exists() else {})
            entry = status.get(mailbox_id, {})
            entry.update(fields)
            status[mailbox_id] = entry
            self.status_path.write_text(json.dumps(status, indent=2, sort_keys=True))
        except Exception:
            pass

    def mailbox_status(self) -> dict:
        try:
            return json.loads(self.status_path.read_text())
        except Exception:
            return {}

    def _move(self, conn, uid: bytes, label: str):
        """Copy to the label and flag the original deleted. Addressed by UID:
        Gmail auto-expunges on \\Deleted, so sequence numbers shift mid-cycle
        and would point at the wrong message from the second move onward."""
        with_label = label.encode() if isinstance(label, str) else label
        try:
            conn.create(with_label)
        except Exception:
            pass
        try:
            conn.uid("COPY", uid, with_label)
            conn.uid("STORE", uid, "+FLAGS", "\\Deleted")
        except Exception:
            conn.uid("STORE", uid, "+FLAGS", "\\Seen")   # never lose mail

    # -- Core cycle -----------------------------------------------------
    def poll_once(self, dry_run: bool = False,
                  mailbox_ids: list[str] | None = None) -> dict:
        """One cycle over every polled mailbox (or just mailbox_ids). A
        mailbox that cannot be opened is ledgered and skipped; the others
        still run, so one client's expired credential never blocks the rest."""
        stats = {"scanned": 0, "accepted": 0, "rejected": 0,
                 "submitted_batches": [], "mailboxes": {}, "failed_mailboxes": []}
        boxes = self.cfg.polled_mailboxes()
        if mailbox_ids is not None:
            boxes = [b for b in boxes if b.id in mailbox_ids]
        for spec in boxes:
            try:
                sub = self._poll_mailbox(spec, dry_run=dry_run)
            except (MailboxAuthError, OSError, imaplib.IMAP4.error) as exc:
                err = str(exc)[:300]
                self.audit.record("mailbox_poll_failed", mailbox=spec.id,
                                  mailbox_key=spec.key, error=err)
                self._write_status(spec.id, key=spec.key,
                                   last_poll=datetime.now(timezone.utc).isoformat(),
                                   last_error=err)
                stats["mailboxes"][spec.id] = {"error": err}
                stats["failed_mailboxes"].append(spec.id)
                continue
            stats["mailboxes"][spec.id] = sub
            for k in ("scanned", "accepted", "rejected"):
                stats[k] += sub[k]
            stats["submitted_batches"] += sub["submitted_batches"]
        return stats

    def _poll_mailbox(self, spec: MailboxSpec, dry_run: bool = False) -> dict:
        stats = {"scanned": 0, "accepted": 0, "rejected": 0, "submitted_batches": []}
        conn = self._open(spec)
        try:
            typ, _ = conn.select(spec.folder)
            if typ != "OK":
                raise MailboxAuthError(
                    f"mailbox {spec.id!r}: folder {spec.folder!r} not selectable")
            _, data = conn.uid("SEARCH", None, "ALL")
            ids = data[0].split() if data and data[0] else []
            for msg_id in ids:                    # msg_id is a UID from here on
                _, hdr = conn.uid("FETCH", msg_id, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                if not hdr or hdr[0] is None:     # vanished between search and fetch
                    continue
                mid = ""
                try:
                    mid = email.message_from_bytes(
                        hdr[0][1], policy=email.policy.default).get("Message-ID", "")
                    mid = str(mid).strip()[:200]
                except Exception:
                    pass
                # Keyed per mailbox: the same mail CC'd to two intake boxes is
                # handled in each (doc-hash dedupe stops a double submission).
                hkey = f"{spec.id}|{mid}" if mid else ""
                if hkey and hkey in self.handled:
                    continue
                # BODY.PEEK: a plain RFC822 fetch sets \Seen as a side effect,
                # which would hide the message from the next UNSEEN search —
                # a dry-run must leave the mailbox exactly as it found it.
                _, msg_data = conn.uid("FETCH", msg_id, "(BODY.PEEK[])")
                if not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                stats["scanned"] += 1
                outcome = self.handle_message(msg, dry_run=dry_run, mailbox=spec)
                if hkey and not dry_run:
                    self.handled.add(hkey)
                    self.handled_path.write_text(json.dumps(sorted(self.handled)))
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
        now = datetime.now(timezone.utc).isoformat()
        self._write_status(spec.id, key=spec.key, last_poll=now, last_ok=now,
                           last_error=None, **{k: stats[k] for k in
                                               ("scanned", "accepted", "rejected")})
        return stats

    def handle_message(self, msg: EmailMessage, dry_run: bool = False,
                       mailbox: MailboxSpec | None = None) -> dict:
        addr = sender_address(msg)
        subject = str(msg.get("Subject", ""))[:200]
        message_id = str(msg.get("Message-ID", ""))[:200]
        # No mailbox given (direct handle_message callers, tests): the
        # allowlist is not scoped, matching the single-mailbox behaviour.
        verdict = validate_message(msg, self.cfg, self.seen, self.validator,
                                   mailbox_id=mailbox.id if mailbox else None)

        base = {
            "sender": addr, "subject": subject, "message_id": message_id,
            "client_id": verdict.client_id, "product": verdict.product,
            "reason": verdict.reason,
        }
        if mailbox is not None:
            base["mailbox"] = mailbox.id
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
    ap.add_argument("--mailbox", action="append", metavar="ID",
                    help="poll only this mailbox id (repeatable)")
    ap.add_argument("--test", action="store_true",
                    help="log in to every configured mailbox, report, exit")
    args = ap.parse_args()

    if args.verify_audit:
        log = EmailAuditLog(STATE_DIR / "email_audit.jsonl")
        ok, detail = log.verify()
        print(f"audit chain: {'VALID' if ok else 'BROKEN'} ({detail})")
        raise SystemExit(0 if ok else 1)

    cfg = EmailIngestConfig.load(Path(args.config))
    ing = EmailIngestor(cfg)

    if args.test:
        boxes = cfg.all_mailboxes()
        if args.mailbox:
            boxes = [b for b in boxes if b.id in args.mailbox]
        bad = 0
        for spec in boxes:
            r = test_connection(spec)
            bad += not r["ok"]
            print(f"[email_ingest] {spec.id:<16} {spec.key:<50} "
                  + (f"OK unseen={r['unseen']} {r['ms']}ms" if r["ok"]
                     else f"FAIL {r['error']}"))
        raise SystemExit(1 if bad else 0)

    boxes = cfg.polled_mailboxes()
    if args.poll:
        print(f"[email_ingest] polling {len(boxes)} mailbox(es) every {args.poll}s:")
        for b in boxes:
            print(f"[email_ingest]   {b.id:<16} {b.key}  auth={b.auth}")
        while True:
            stats = ing.poll_once(dry_run=args.dry_run, mailbox_ids=args.mailbox)
            print(f"[email_ingest] {datetime.now().isoformat(timespec='seconds')} "
                  f"{stats}")
            time.sleep(args.poll)
    else:
        print(ing.poll_once(dry_run=args.dry_run, mailbox_ids=args.mailbox))


if __name__ == "__main__":
    main()
