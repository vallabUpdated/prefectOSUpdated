"""Role-based access for PrefectOS: the 'User' role and the admin-only routes.

One policy, enforced at two choke points so new routes are covered by default:

  * Flask   (server.py)     -> install_flask(app)    before_request hook
  * FastAPI (batch_api.py)  -> install_fastapi(app)  pure-ASGI middleware

How a request is judged
-----------------------
1. The caller's key comes from the X-API-Key header only (never the query
   string, which leaks into logs). The role is looked up SERVER-SIDE; any role
   the client puts in a request body or localStorage is ignored.
2. Key -> role:
     admin-issued keys in data/api_keys.json   (active and not expired)
     PREFECTOS_ADMIN_KEYS   (comma-separated)  -> "System Admin"
     PREFECTOS_API_KEYS     (comma-separated)  -> "Licensee"
     built-in demo keys, only while PREFECTOS_API_KEYS is unset
   No key, an unknown key, or an expired/revoked key is "anonymous".
3. 'User' and 'anonymous' are the restricted roles. Every other role keeps
   today's behaviour, except the three admin-only rules below.

Rollout switch
--------------
PREFECTOS_ENFORCE_ROLES unset/0 -> LOG-ONLY: a request the policy would block
is logged as "ROLE-GUARD (log-only)" and still served. Watch the log, then set
PREFECTOS_ENFORCE_ROLES=1 to start returning 403.

The rules mirror the 'User Permissions' sheet in PrefectOS_User_Role_Permissions.xlsx.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("prefectos.access")

ADMIN_ROLES = {"system admin", "admin"}
RESTRICTED_ROLES = {"user", "anonymous"}

# Same demo keys the sign-in dialog and institution_settings_api ship with.
_DEMO_KEYS = {
    "prf_live_admin_8849":       ("Sarah Jenkins", "System Admin"),
    "prf_live_underwriter_9921": ("David Vance",   "Lead Underwriter"),
    "prf_live_risk_3342":        ("Elena Rostova", "Risk Officer"),
    "prf_live_auditor_1105":     ("Marcus Vance",  "Internal Auditor"),
}

_WRITE = ("POST", "PUT", "PATCH", "DELETE")

# (methods or None for all, path regex, level, label). First match wins.
#   "admin"   -> only ADMIN_ROLES may call it
#   "no_user" -> 'User' and anonymous are refused; other roles unchanged
_RULES = [
    (("POST",), r"/run",                          "admin",   "Start pipeline run"),
    (None,      r"/loan/(browse|mkdir)",          "admin",   "Server file browsing"),
    (None,      r"/api/admin/keys(/.*)?",         "admin",   "Admin keys"),
    (("POST",), r"/approve/.+",                   "no_user", "Approve / reject gates"),
    (("POST",), r"/(cancel|pause|resume|stop)/.+", "no_user", "Pipeline run control"),
    (_WRITE,    r"/governance(/.*)?",             "no_user", "Governance changes"),
    (_WRITE,    r"/institution-settings",         "no_user", "Settings write"),
    (_WRITE,    r"/email/(settings|templates)",   "no_user", "Settings write"),
    (_WRITE,    r"/loan/prompts",                 "no_user", "Settings write"),
    (("POST",), r"/loan/policy/index",            "no_user", "Settings write"),
    (None,      r"/email/mailboxes(/.*)?",        "no_user", "Email mailboxes"),
    (None,      r"/cbs(/.*)?",                    "no_user", "Core banking"),
]
_COMPILED = [(m, re.compile(p + r"$"), lvl, label) for m, p, lvl, label in _RULES]


# ── Identity ────────────────────────────────────────────────────────────────

@dataclass
class Identity:
    role: str = "anonymous"
    name: str = ""
    source: str = "none"          # issued | admin_env | env | demo | none
    reason: str | None = None     # why a presented key was not accepted
    expires_at: str | None = None


def _keys_path() -> Path:
    return Path(os.environ.get("PREFECTOS_KEYS_PATH")
                or Path(__file__).parent / "data" / "api_keys.json")


def _csv_env(name: str) -> list[str]:
    return [k.strip() for k in os.environ.get(name, "").split(",") if k.strip()]


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def lookup_issued(key: str):
    """Find an admin-issued key. Returns (entry, problem).

    entry is None when the key is not an issued one. problem is 'revoked',
    'expired' or 'invalid expiry' when it is issued but unusable.
    """
    try:
        entries = json.loads(_keys_path().read_text(encoding="utf-8"))
    except Exception:
        return None, None
    for e in entries if isinstance(entries, list) else []:
        if not _same(str(e.get("key", "")), key):
            continue
        if str(e.get("status", "ACTIVE")).upper() != "ACTIVE":
            return e, "revoked"
        exp = e.get("expires_at")
        if exp:
            try:
                if datetime.now() >= datetime.fromisoformat(exp):
                    return e, "expired"
            except ValueError:
                return e, "invalid expiry"
        return e, None
    return None, None


def resolve(key: str | None) -> Identity:
    key = (key or "").strip()
    if len(key) < 6:
        return Identity(reason="no key" if not key else "unknown key")

    entry, problem = lookup_issued(key)
    if entry is not None:
        if problem:
            return Identity(reason=problem, name=entry.get("name") or "",
                            source="issued", expires_at=entry.get("expires_at"))
        return Identity(role=(entry.get("role") or "User").strip(),
                        name=entry.get("name") or "", source="issued",
                        expires_at=entry.get("expires_at"))

    if any(_same(k, key) for k in _csv_env("PREFECTOS_ADMIN_KEYS")):
        return Identity(role="System Admin", name="Administrator", source="admin_env")

    env_keys = _csv_env("PREFECTOS_API_KEYS")
    if env_keys:
        if any(_same(k, key) for k in env_keys):
            return Identity(role="Licensee", name="Licensee", source="env")
        return Identity(reason="unknown key")

    demo = _DEMO_KEYS.get(key)
    if demo:
        return Identity(role=demo[1], name=demo[0], source="demo")
    return Identity(reason="unknown key")


# ── Policy ──────────────────────────────────────────────────────────────────

@dataclass
class Decision:
    allowed: bool
    role: str
    label: str = ""
    message: str = ""
    blocked: bool = False         # allowed is False AND enforcement is on


def enforcing() -> bool:
    return os.environ.get("PREFECTOS_ENFORCE_ROLES", "").strip().lower() in ("1", "true", "yes", "on")


def _norm_path(path: str) -> str:
    path = re.sub(r"/+", "/", path or "/")
    return path.rstrip("/") or "/"


def check(method: str, path: str, key: str | None) -> Decision:
    method = (method or "GET").upper()
    if method == "HEAD":
        method = "GET"
    path = _norm_path(path)

    for methods, rx, level, label in _COMPILED:
        if methods is not None and method not in methods:
            continue
        if not rx.match(path):
            continue
        ident = resolve(key)
        role = ident.role.lower()
        if level == "admin":
            ok = role in ADMIN_ROLES
            need = "an administrator key"
        else:
            ok = role not in RESTRICTED_ROLES
            need = "a role with this permission"
        if ok:
            return Decision(True, ident.role, label)
        why = f" ({ident.reason})" if ident.reason else ""
        msg = f"{label} requires {need}; your access is '{ident.role}'{why}."
        d = Decision(False, ident.role, label, msg, blocked=enforcing())
        log.warning("ROLE-GUARD (%s): %s %s role=%s rule=%s",
                    "BLOCKED" if d.blocked else "log-only, would deny",
                    method, path, ident.role, label)
        return d
    return Decision(True, "n/a")


# ── Framework hooks ─────────────────────────────────────────────────────────

def install_flask(app) -> None:
    """Guard every Flask route, including the /email and /governance proxies."""
    from flask import jsonify, request

    @app.before_request
    def _role_guard():
        if request.method == "OPTIONS":
            return None
        d = check(request.method, request.path, request.headers.get("X-API-Key"))
        if d.blocked:
            return jsonify({"detail": d.message}), 403
        return None


def install_fastapi(app) -> None:
    """Guard every FastAPI route. Add BEFORE CORSMiddleware so a 403 still
    carries CORS headers (the last-added middleware is the outermost)."""

    class _RoleGuard:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["method"] != "OPTIONS":
                hdrs = {k.decode("latin-1").lower(): v.decode("latin-1")
                        for k, v in scope["headers"]}
                d = check(scope["method"], scope["path"], hdrs.get("x-api-key"))
                if d.blocked:
                    body = json.dumps({"detail": d.message}).encode()
                    await send({"type": "http.response.start", "status": 403,
                                "headers": [(b"content-type", b"application/json"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
            await self.inner(scope, receive, send)

    app.add_middleware(_RoleGuard)
