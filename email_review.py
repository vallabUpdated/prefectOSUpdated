# Part of the PrefectOS core package — email intake review, queue routing,
# and admin settings (valid inboxes + document templates).
"""Human-in-the-loop review + configuration surface for email intake.

REST surface (mounted on the batch API app):
    GET    /email/intake                        list intakes (newest first)
    GET    /email/intake/{id}                   detail incl. email body
    GET    /email/intake/{id}/documents/{name}  download one document
    POST   /email/intake/{id}/process           submit to the routed queue
    POST   /email/intake/{id}/discard           reject with a reason

    GET    /email/settings                      connector config (no secrets)
    PUT    /email/settings                      update routes/flags → sealed
    GET    /email/templates                     doc templates + document sets
    PUT    /email/templates                     update → sealed to audit chain

Queue routing: config "queues" maps product -> {"api": url}; anything
unmapped goes to the default ingest_api. Submitted user_id is
"<client_id>::<queue>" so downstream workers and the batch ledger stay
segregated per client per product with zero batch-API changes.

Settings writes are sealed into the same hash-chained email audit log
(routes_updated / template_updated with a content hash), because a
template or allowlist change silently changes what gets accepted from
every client thereafter — an auditor must be able to see when and by
whom the rules moved.

Wire into batch_api.py:
    from email_review import router as email_router
    app.include_router(email_router)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

STATE_DIR = Path(os.getenv("EMAIL_INGEST_STATE", "project_output/email_ingest"))
PENDING_ROOT = STATE_DIR / "pending"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._ \-]+$")


# ── Pending store (used by the connector to park validated intakes) ────
class PendingStore:
    def __init__(self, root: Path = PENDING_ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def park(self, *, sender: str, subject: str, message_id: str,
             client_id: str, product: str | None, body_text: str,
             attachments: list[tuple[str, bytes]],
             doc_types: dict[str, str | None]) -> str:
        intake_id = datetime.now(timezone.utc).strftime("%Y%m%d") \
            + "-" + uuid.uuid4().hex[:8]
        d = self.root / intake_id
        (d / "docs").mkdir(parents=True)
        for name, payload in attachments:
            (d / "docs" / Path(name).name).write_bytes(payload)
        manifest = {
            "intake_id": intake_id,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "sender": sender, "subject": subject, "message_id": message_id,
            "client_id": client_id, "product": product,
            "body_text": body_text[:20000],
            "documents": [
                {"name": Path(n).name, "doc_type": doc_types.get(n),
                 "size": len(p)} for n, p in attachments
            ],
        }
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return intake_id

    def list(self) -> list[dict]:
        items = []
        for mf in sorted(self.root.glob("*/manifest.json"), reverse=True):
            try:
                m = json.loads(mf.read_text())
                items.append({k: m[k] for k in
                              ("intake_id", "received_at", "status", "sender",
                               "subject", "client_id", "product")}
                             | {"n_docs": len(m.get("documents", []))})
            except Exception:
                continue
        return items

    def manifest(self, intake_id: str) -> dict:
        mf = self.root / intake_id / "manifest.json"
        if not mf.exists():
            raise KeyError(intake_id)
        return json.loads(mf.read_text())

    def doc_path(self, intake_id: str, name: str) -> Path:
        if not _SAFE_NAME.match(name):
            raise KeyError(name)
        p = (self.root / intake_id / "docs" / name).resolve()
        if not str(p).startswith(str((self.root / intake_id).resolve())) \
                or not p.exists():
            raise KeyError(name)
        return p

    def set_status(self, intake_id: str, status: str, **extra):
        m = self.manifest(intake_id)
        m["status"] = status
        m.update(extra)
        (self.root / intake_id / "manifest.json").write_text(
            json.dumps(m, indent=2))
        return m


# ── Queue routing ──────────────────────────────────────────────────────
def resolve_queue(product: str | None, default_api: str,
                  queue_map: dict[str, dict] | None) -> tuple[str, str]:
    """Returns (api_url, queue_name); unmapped products → default API."""
    qname = product or "general"
    if queue_map and qname in queue_map:
        return queue_map[qname].get("api", default_api), qname
    return default_api, qname


# ── FastAPI router ─────────────────────────────────────────────────────
router = APIRouter(prefix="/email", tags=["email-intake"])
store = PendingStore()

# late-bound so tests can inject; defaults pull from the connector module
def _submit(api_url: str, user_id: str, files):
    from email_ingest import submit_to_ingest
    return submit_to_ingest(api_url, user_id, files)


def _config():
    from email_ingest import CONFIG_PATH, EmailIngestConfig
    return EmailIngestConfig.load(CONFIG_PATH)


def _audit():
    from email_ingest import EmailAuditLog
    return EmailAuditLog(STATE_DIR / "email_audit.jsonl")


@router.get("/intake")
def list_intake():
    return {"intakes": store.list()}


@router.get("/intake/{intake_id}")
def intake_detail(intake_id: str):
    try:
        return store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")


@router.get("/intake/{intake_id}/documents/{name}")
def download_document(intake_id: str, name: str):
    try:
        path = store.doc_path(intake_id, name)
    except KeyError:
        raise HTTPException(404, "unknown document")
    return FileResponse(path, media_type="application/pdf", filename=name)


@router.post("/intake/{intake_id}/process")
def process_intake(intake_id: str, approver: str = "unknown"):
    try:
        m = store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")
    if m["status"] != "pending":
        raise HTTPException(409, f"intake is {m['status']}, not pending")

    cfg = _config()
    queue_map = getattr(cfg, "queues", None) or {}
    api_url, queue = resolve_queue(m["product"], cfg.ingest_api, queue_map)
    user_id = f"{m['client_id']}::{queue}"

    files = [(d["name"], store.doc_path(intake_id, d["name"]).read_bytes())
             for d in m["documents"]]
    try:
        result = _submit(api_url, user_id, files)
    except Exception as exc:
        _audit().record("process_failed", intake_id=intake_id,
                        queue=queue, approver=approver, error=str(exc)[:300])
        raise HTTPException(502, f"queue submission failed: {exc}")

    m = store.set_status(intake_id, "processed",
                         batch_id=result.get("batch_id"), queue=queue,
                         processed_by=approver,
                         processed_at=datetime.now(timezone.utc).isoformat())
    _audit().record("intake_processed", intake_id=intake_id,
                    sender=m["sender"], client_id=m["client_id"],
                    queue=queue, batch_id=result.get("batch_id"),
                    approver=approver, n_docs=len(files))
    return {"intake_id": intake_id, "status": "processed",
            "queue": queue, "batch_id": result.get("batch_id")}


@router.post("/intake/{intake_id}/discard")
def discard_intake(intake_id: str, reason: str = "", approver: str = "unknown"):
    try:
        m = store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")
    if m["status"] != "pending":
        raise HTTPException(409, f"intake is {m['status']}, not pending")
    if len(reason.strip()) < 10:
        raise HTTPException(422, "a rejection reason (≥10 chars) is required")
    m = store.set_status(intake_id, "discarded", discard_reason=reason,
                         discarded_by=approver)
    _audit().record("intake_discarded", intake_id=intake_id,
                    sender=m["sender"], client_id=m["client_id"],
                    reason=reason, approver=approver)
    return {"intake_id": intake_id, "status": "discarded"}


# ── Admin settings: valid inboxes + document templates ─────────────────
def _config_path() -> Path:
    from email_ingest import CONFIG_PATH
    return Path(CONFIG_PATH)


def _templates_path() -> Path:
    cfg = json.loads(_config_path().read_text())
    return Path(cfg.get("templates_file") or "doc_templates.json")


def _sealed_write(path: Path, data: dict, event: str, approver: str):
    text = json.dumps(data, indent=2)
    path.write_text(text)
    _audit().record(event, file=str(path), approver=approver,
                    content_sha256=hashlib.sha256(text.encode()).hexdigest())


@router.get("/settings")
def get_settings():
    """Connector config. Contains NO secrets by design — the mailbox
    password lives only in the EMAIL_INGEST_PASSWORD env var."""
    try:
        return json.loads(_config_path().read_text())
    except FileNotFoundError:
        raise HTTPException(404, "email_ingest_config.json not found")


@router.put("/settings")
def put_settings(settings: dict = Body(...), approver: str = "unknown"):
    for key in ("imap_host", "imap_user", "routes"):
        if key not in settings:
            raise HTTPException(422, f"missing required field: {key}")
    if any(k in json.dumps(settings).lower()
           for k in ("password", "secret", "token")):
        raise HTTPException(422,
            "settings must not contain credentials — use EMAIL_INGEST_PASSWORD")
    for r in settings["routes"]:
        if not r.get("client_id") or not r.get("senders"):
            raise HTTPException(422, "each route needs client_id and senders")
    _sealed_write(_config_path(), settings, "routes_updated", approver)
    return {"ok": True, "note": "connector applies changes on its next poll"}


@router.get("/templates")
def get_templates():
    try:
        return json.loads(_templates_path().read_text())
    except FileNotFoundError:
        raise HTTPException(404, "doc_templates.json not found")


@router.put("/templates")
def put_templates(templates: dict = Body(...), approver: str = "unknown"):
    if "templates" not in templates or "document_sets" not in templates:
        raise HTTPException(422, "need 'templates' and 'document_sets'")
    seen_types = set()
    for t in templates["templates"]:
        if not t.get("doc_type") or not t.get("label"):
            raise HTTPException(422, "each template needs doc_type and label")
        seen_types.add(t["doc_type"])
    for product, req in templates["document_sets"].items():
        unknown = [d for d in req if d not in seen_types]
        if unknown:
            raise HTTPException(
                422, f"document_sets[{product}] references undefined "
                     f"doc_types: {unknown}")
    _sealed_write(_templates_path(), templates, "template_updated", approver)
    return {"ok": True, "note": "connector applies changes on its next poll"}
