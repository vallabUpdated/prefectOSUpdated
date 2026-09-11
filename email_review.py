# Part of the PrefectOS core package — email intake review, queue routing,
# and admin settings (valid inboxes + document templates).
"""Human-in-the-loop review + configuration surface for email intake.

REST surface (mounted on the batch API app):
    GET    /email/intake                        list intakes (newest first)
    GET    /email/intake/{id}                   detail incl. email body
    GET    /email/intake/{id}/documents/{name}  download one document
    POST   /email/intake/{id}/process           run through the processing engine
                                                (?rerun=1 re-runs a processed intake;
                                                 the previous run is kept in "runs")
    GET    /email/intake/{id}/report?kind=      eligibility report (html|md|json)
    POST   /email/intake/{id}/discard           reject with a reason

    GET    /email/settings                      connector config (no secrets)
    PUT    /email/settings                      update routes/flags → sealed
    GET    /email/mailboxes                     every mailbox + poll health
    POST   /email/mailboxes/test                live IMAP login check (body:
                                                {"mailbox": <spec>} or {"id"})
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

import urllib.error
import urllib.request

# Email-intake product -> loan_processing type. Anything unmapped runs as
# "general" (the operator's general-review prompt) rather than being refused.
PRODUCT_TO_TYPE = {
    "home_loan": "home", "vehicle_loan": "vehicle", "personal_loan": "personal",
    "mortgage": "mortgage", "mortgage_loan": "mortgage",
    "kyc": "kyc", "statement": "account_statement",
}

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
        for k, v in extra.items():
            if v is None:
                m.pop(k, None)          # None clears a field (re-run resets)
            else:
                m[k] = v
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
        m = store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")
    m["result"] = _result_for(m)
    # What "Process documents" would run: the engine type for the product
    # and the operator's configured prompt for it (editable per intake).
    if m.get("status") in ("pending", "processed"):
        ptype, label = processing_type_for(m.get("product"))
        try:
            from loan_processing import prompt_for
            m["default_prompt"] = prompt_for(ptype)
        except Exception:
            m["default_prompt"] = ""
        m.setdefault("processing_type", ptype)
        m.setdefault("processing_label", label)
        m["run_active"] = _engine_job_active(m, _config()) if m.get("status") == "processed" else False
    return m


@router.get("/intake/{intake_id}/documents/{name}")
def download_document(intake_id: str, name: str):
    try:
        path = store.doc_path(intake_id, name)
    except KeyError:
        raise HTTPException(404, "unknown document")
    return FileResponse(path, media_type="application/pdf", filename=name)


def _result_for(m: dict) -> dict | None:
    """Final numbers for a processed intake, read from the engine's
    summary.json in the run folder so they survive a server restart."""
    run_dir = m.get("run_dir")
    if not run_dir:
        return None
    try:
        snap = json.loads((Path(run_dir) / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    keys = ("status", "decision", "tokens_in", "tokens_out", "cost_usd", "elapsed_s",
            "model", "provider", "done", "total", "failed", "finished_at", "error",
            "docs_clean", "docs_escalated", "ai_share", "mode")
    out = {k: snap.get(k) for k in keys}
    # Reports only exist once the run is over: a summary still saying
    # "running" beside them is a snapshot taken a beat too early.
    if out.get("status") in ("running", "queued") and             (Path(run_dir) / "eligibility_report.json").exists():
        out["status"] = "completed"
    return out


def processing_type_for(product: str | None) -> tuple[str, str]:
    """(engine type id, label) for an intake product."""
    from loan_processing import type_spec
    ptype = PRODUCT_TO_TYPE.get(product or "", "general")
    spec = type_spec(ptype) or {}
    return ptype, spec.get("label", ptype)


def _run_via_engine(m: dict, intake_dir: Path, cfg, bank_name: str,
                    policy_path: str, prompt: str = "") -> dict:
    """POST the pack to server.py /loan/process. An empty prompt means the
    engine applies the operator's configured prompt for the type; a reviewer
    may override it for this one intake."""
    from loan_processing import type_spec
    ptype, label = processing_type_for(m.get("product"))
    spec = type_spec(ptype) or {}
    body = {
        "loan_type": ptype,
        "input_path": str(intake_dir / "docs"),
        "output_path": str(intake_dir / "output"),
        "prompt": (prompt or "").strip(),
        "mode": spec.get("default_mode", "deterministic"),
        "bank_name": bank_name or "",
        "policy_path": policy_path or "",
        "actor": {"user_name": m.get("approver", "")},
    }
    base = (getattr(cfg, "processing_api", "") or "http://127.0.0.1:5055").rstrip("/")
    req = urllib.request.Request(
        f"{base}/loan/process", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            out = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail).get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(f"processing engine refused the job ({e.code}): {detail}")
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"processing engine unreachable at {base}: {e}")
    return {"job_id": out.get("job_id"), "run_dir": out.get("run_dir"),
            "run_folder": out.get("run_folder"), "processing_type": ptype,
            "processing_label": label}


RUN_KEYS = ("engine", "job_id", "run_dir", "run_folder", "processing_type",
            "processing_label", "processed_by", "processed_at", "prompt",
            "prompt_edited", "policy_note", "queue", "batch_id")


def _engine_job_active(m: dict, cfg) -> bool:
    """Ask the engine whether the intake's current job is still running.
    Unreachable engine or unknown job => not active (the summary decides)."""
    job_id = m.get("job_id")
    if not job_id or m.get("engine") != "loan":
        return False
    base = (getattr(cfg, "processing_api", "") or "http://127.0.0.1:5055").rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/loan/jobs/{job_id}", timeout=10) as resp:
            return json.loads(resp.read().decode()).get("status") in ("queued", "running")
    except Exception:
        return False


@router.post("/intake/{intake_id}/process")
def process_intake(intake_id: str, approver: str = "unknown",
                   bank_name: str = "", policy_path: str = "",
                   rerun: bool = False, body: dict | None = Body(None)):
    """Body (optional JSON): {"prompt": "..."} — a reviewer's prompt for this
    intake only. Empty/omitted = the configured prompt for the product type.
    rerun=true processes an already-processed intake again (e.g. with a new
    prompt); the previous run's details are appended to the manifest's "runs"."""
    try:
        m = store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")
    cfg = _config()
    if m["status"] == "processed" and rerun:
        if _engine_job_active(m, cfg):
            raise HTTPException(409, "the previous run is still in progress")
        previous = {k: m[k] for k in RUN_KEYS if k in m}
        previous["result"] = _result_for(m)
        runs = list(m.get("runs") or []) + [previous]
        m = store.set_status(intake_id, "pending", runs=runs,
                             **{k: None for k in RUN_KEYS if k in m})
        _audit().record("intake_rerun_requested", intake_id=intake_id,
                        approver=approver, previous_job_id=previous.get("job_id"),
                        run_number=len(runs) + 1)
    if m["status"] != "pending":
        raise HTTPException(409, f"intake is {m['status']}, not pending")
    # Called directly (tests, other code) `body` may be FastAPI's Body marker.
    prompt = ((body if isinstance(body, dict) else {}).get("prompt") or "").strip()
    if prompt and len(prompt) < 20:
        raise HTTPException(422, "prompt must be at least 20 characters (or empty for the configured one)")

    if (getattr(cfg, "processing_engine", "loan") or "loan") == "loan":
        intake_dir = store.root / intake_id
        # The workspace's policy pack is optional context. A path that no
        # longer exists (stale setting, other machine) must not block the
        # pack from being processed — run without it and say so.
        policy_note = ""
        if policy_path and not Path(policy_path).expanduser().is_dir():
            policy_note = f"policy pack not found, processed without it: {policy_path}"
            policy_path = ""
        try:
            job = _run_via_engine({**m, "approver": approver}, intake_dir, cfg,
                                  bank_name, policy_path, prompt)
        except RuntimeError as exc:
            _audit().record("process_failed", intake_id=intake_id,
                            engine="loan", approver=approver, error=str(exc)[:300])
            raise HTTPException(502, str(exc))
        if not prompt:
            from loan_processing import prompt_for
            prompt_used = prompt_for(job["processing_type"])
        else:
            prompt_used = prompt
        m = store.set_status(intake_id, "processed", engine="loan", **job,
                             processed_by=approver,
                             processed_at=datetime.now(timezone.utc).isoformat(),
                             prompt=prompt_used, prompt_edited=bool(prompt),
                             **({"policy_note": policy_note} if policy_note else {}))
        _audit().record("intake_processed", intake_id=intake_id,
                        sender=m["sender"], client_id=m["client_id"],
                        engine="loan", processing_type=job["processing_type"],
                        job_id=job["job_id"], run_dir=job["run_dir"],
                        prompt_edited=bool(prompt),
                        prompt_sha256=hashlib.sha256(prompt_used.encode()).hexdigest(),
                        approver=approver, n_docs=len(m["documents"]))
        return {"intake_id": intake_id, "status": "processed", "engine": "loan", **job,
                "processed_by": m.get("processed_by"), "processed_at": m.get("processed_at"),
                "prompt": prompt_used, "prompt_edited": bool(prompt),
                "policy_note": policy_note or None}

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


@router.get("/intake/{intake_id}/report")
def intake_report(intake_id: str, kind: str = "html"):
    """The engine's eligibility report for a processed intake, served from
    the intake's own run folder (independent of the engine's job cache)."""
    try:
        m = store.manifest(intake_id)
    except KeyError:
        raise HTTPException(404, "unknown intake")
    kind = (kind or "html").lower()
    media = {"html": "text/html", "md": "text/markdown", "json": "application/json"}
    if kind not in media:
        raise HTTPException(400, "kind must be html, md or json")
    if not m.get("run_dir"):
        raise HTTPException(404, "intake has not been processed")
    path = Path(m["run_dir"]) / f"eligibility_report.{kind}"
    if not path.exists():
        raise HTTPException(404, "report not generated yet")
    # Inline, like the loan-card reports: the HTML opens in the tab; the
    # browser still offers "save as" with a sensible name.
    return FileResponse(path, media_type=media[kind], headers={
        "Content-Disposition": f'inline; filename="{intake_id}_report.{kind}"'})


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


# Keys that would mean a credential was pasted into the config. The env-var
# NAME fields (secret_env) are fine; their values are checked separately.
_CREDENTIAL_KEYS = {"password", "imap_password", "secret", "client_secret",
                    "token", "access_token", "refresh_token", "private_key",
                    "app_password"}


def _reject_credentials(obj, path="settings"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in _CREDENTIAL_KEYS:
                raise HTTPException(422,
                    f"{path}.{k}: settings must not contain credentials — "
                    "name an environment variable in secret_env instead")
            _reject_credentials(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_credentials(v, f"{path}[{i}]")


@router.get("/settings")
def get_settings():
    """Connector config. Contains NO secrets by design — each mailbox names
    the env var that holds its secret (default: EMAIL_INGEST_PASSWORD)."""
    try:
        return json.loads(_config_path().read_text())
    except FileNotFoundError:
        raise HTTPException(404, "email_ingest_config.json not found")


@router.put("/settings")
def put_settings(settings: dict = Body(...), approver: str = "unknown"):
    from email_ingest import EmailIngestConfig
    for key in ("imap_host", "imap_user", "routes"):
        if key not in settings:
            raise HTTPException(422, f"missing required field: {key}")
    _reject_credentials(settings)
    for r in settings["routes"]:
        if not r.get("client_id") or not r.get("senders"):
            raise HTTPException(422, "each route needs client_id and senders")
    for m in settings.get("mailboxes", []):
        for key in ("id", "imap_host", "imap_user"):
            if not m.get(key):
                raise HTTPException(422, f"each mailbox needs {key}")
    # Let the dataclasses enforce auth/provider/env-var-name/binding rules
    # so the UI and the connector can never disagree on what is valid.
    try:
        EmailIngestConfig.from_dict(settings)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    _sealed_write(_config_path(), settings, "routes_updated", approver)
    return {"ok": True, "note": "connector applies changes on its next poll"}


@router.get("/mailboxes")
def list_mailboxes():
    """Every mailbox the connector knows (default + dedicated), which routes
    bind to it, whether its secret is present in this process's env, and
    the last poll outcome recorded by the connector."""
    from email_ingest import EmailIngestor
    try:
        cfg = _config()
    except (FileNotFoundError, TypeError, ValueError) as e:
        raise HTTPException(422, f"config invalid: {e}")
    status = EmailIngestor(cfg, imap_factory=lambda s: None,
                           state_dir=STATE_DIR).mailbox_status()
    polled = {m.id for m in cfg.polled_mailboxes()}
    out = []
    for m in cfg.all_mailboxes():
        out.append({
            **m.public(),
            "routes": [r.client_id for r in cfg.routes_for_mailbox(m.id)],
            "polled": m.id in polled,
            "status": status.get(m.id, {}),
        })
    return {"mailboxes": out}


@router.post("/mailboxes/test")
def test_mailbox(body: dict = Body(...)):
    """Log in to one mailbox and count unseen mail. Either {"id": "<id>"}
    for a saved mailbox or {"mailbox": {...spec}} for an unsaved draft.
    Reads only; moves nothing; the secret never leaves the server."""
    from email_ingest import MailboxSpec, test_connection
    _reject_credentials(body, "body")
    try:
        if "mailbox" in body:
            spec = MailboxSpec(**body["mailbox"])
        else:
            spec = _config().mailbox_by_id(body.get("id", ""))
            if spec is None:
                raise HTTPException(404, f"mailbox {body.get('id')!r} not found")
    except (TypeError, ValueError) as e:
        raise HTTPException(422, str(e))
    return test_connection(spec)


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
