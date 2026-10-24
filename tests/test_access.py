"""Tests for access.py: the 'User' role, 48-hour keys and the admin-only routes.

Run:  python -m pytest tests/test_access.py -q
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import access  # noqa: E402

NOW = datetime.now()
USER_KEY = "prf_live_user_0123456789abcdef"
EXPIRED_KEY = "prf_live_user_expiredexpired00"
REVOKED_KEY = "prf_live_user_revokedrevoked00"
APPROVER_KEY = "prf_live_approver_0123456789ab"
ADMIN_KEY = "prf_live_admin_issuedissued00"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    keys = tmp_path / "api_keys.json"
    keys.write_text(json.dumps([
        {"key": USER_KEY, "name": "Guest", "role": "User", "status": "ACTIVE",
         "expires_at": (NOW + timedelta(hours=48)).isoformat()},
        {"key": EXPIRED_KEY, "name": "Old", "role": "User", "status": "ACTIVE",
         "expires_at": (NOW - timedelta(minutes=1)).isoformat()},
        {"key": REVOKED_KEY, "name": "Gone", "role": "User", "status": "REVOKED", "expires_at": None},
        {"key": APPROVER_KEY, "name": "Ann", "role": "Approver", "status": "ACTIVE", "expires_at": None},
        {"key": ADMIN_KEY, "name": "Root", "role": "System Admin", "status": "ACTIVE", "expires_at": None},
    ]))
    monkeypatch.setenv("PREFECTOS_KEYS_PATH", str(keys))
    monkeypatch.delenv("PREFECTOS_API_KEYS", raising=False)
    monkeypatch.delenv("PREFECTOS_ADMIN_KEYS", raising=False)
    monkeypatch.setenv("PREFECTOS_ENFORCE_ROLES", "1")


# ── The matrix: (method, path) ──────────────────────────────────────────────
ALLOWED_FOR_USER = [
    ("POST", "/loan/scan"), ("POST", "/loan/process"), ("GET", "/loan/jobs/j1"),
    ("GET", "/loan/report/j1"), ("GET", "/loan/document"), ("GET", "/loan/stream/j1"),
    ("GET", "/runs"), ("GET", "/live-runs"), ("GET", "/ledger/r1"), ("GET", "/ledger/r1/verify"),
    ("GET", "/comprehension/r1"), ("GET", "/app-status/r1"), ("GET", "/stream/r1"),
    ("POST", "/chat"), ("GET", "/chat/status"),
    ("GET", "/docx/r1/html"), ("GET", "/loan/documents.zip"),
    ("GET", "/ledger/activity"), ("POST", "/ledger/activity"), ("GET", "/ledger/activity/export"),
    ("GET", "/institution-settings"), ("GET", "/email/settings"), ("GET", "/governance/packs"),
    ("POST", "/ingest/batches"), ("GET", "/auth/whoami"), ("GET", "/"),
]
DENIED_FOR_USER = [
    ("POST", "/approve/r1"),
    ("POST", "/run"), ("POST", "/cancel/r1"), ("POST", "/pause/r1"),
    ("POST", "/resume/r1"), ("POST", "/stop/r1"),
    ("POST", "/governance/packs/x/activate"), ("POST", "/governance/packs/x/deactivate"),
    ("POST", "/governance/freeze"), ("POST", "/governance/release"), ("POST", "/governance/replay"),
    ("PUT", "/institution-settings"), ("PUT", "/email/settings"), ("PUT", "/email/templates"),
    ("PUT", "/loan/prompts"), ("POST", "/loan/policy/index"),
    ("GET", "/api/admin/keys"), ("POST", "/api/admin/keys/create"),
    ("GET", "/email/mailboxes"), ("POST", "/email/mailboxes/test"),
    ("POST", "/cbs/tx/cash"), ("POST", "/cbs/payments/transfer"), ("POST", "/cbs/eod/run"),
    ("GET", "/loan/browse"), ("POST", "/loan/mkdir"),
]
ADMIN_ONLY = [("POST", "/run"), ("GET", "/loan/browse"), ("POST", "/loan/mkdir"),
              ("GET", "/api/admin/keys"), ("POST", "/api/admin/keys/create")]


@pytest.mark.parametrize("method,path", ALLOWED_FOR_USER)
def test_user_allowed(method, path):
    assert access.check(method, path, USER_KEY).allowed, (method, path)


@pytest.mark.parametrize("method,path", DENIED_FOR_USER)
def test_user_denied(method, path):
    d = access.check(method, path, USER_KEY)
    assert not d.allowed and d.blocked, (method, path)


@pytest.mark.parametrize("method,path", DENIED_FOR_USER)
def test_anonymous_treated_as_user(method, path):
    assert not access.check(method, path, None).allowed


@pytest.mark.parametrize("key", [EXPIRED_KEY, REVOKED_KEY, "totally-unknown-key-123"])
def test_bad_keys_are_restricted(key):
    assert not access.check("POST", "/approve/r1", key).allowed
    assert access.resolve(key).role == "anonymous"


def test_expired_and_revoked_reasons():
    assert access.resolve(EXPIRED_KEY).reason == "expired"
    assert access.resolve(REVOKED_KEY).reason == "revoked"


def test_approver_keeps_todays_access_but_not_admin_only():
    for m, p in DENIED_FOR_USER:
        allowed = access.check(m, p, APPROVER_KEY).allowed
        assert allowed == ((m, p) not in ADMIN_ONLY), (m, p)


def test_admin_can_do_everything():
    for m, p in DENIED_FOR_USER:
        assert access.check(m, p, ADMIN_KEY).allowed, (m, p)


def test_env_admin_key(monkeypatch):
    monkeypatch.setenv("PREFECTOS_ADMIN_KEYS", "envadminkey-999999")
    assert access.check("POST", "/api/admin/keys/create", "envadminkey-999999").allowed


def test_demo_keys_only_while_env_keys_unset(monkeypatch):
    assert access.check("POST", "/approve/r1", "prf_live_underwriter_9921").allowed
    assert access.check("POST", "/run", "prf_live_admin_8849").allowed
    monkeypatch.setenv("PREFECTOS_API_KEYS", "somelicensee-key-1")
    assert not access.check("POST", "/run", "prf_live_admin_8849").allowed        # demo keys off
    assert access.check("POST", "/approve/r1", "somelicensee-key-1").allowed      # Licensee ok
    assert not access.check("POST", "/run", "somelicensee-key-1").allowed         # but not admin-only


def test_path_tricks_do_not_bypass():
    for p in ("//approve/r1", "/approve/r1/", "///run", "/run/"):
        assert not access.check("POST", p, USER_KEY).allowed, p


def test_head_is_treated_as_get():
    assert access.check("HEAD", "/runs", USER_KEY).allowed


def test_role_in_request_is_ignored_server_side():
    # Only the key matters: nothing in check() takes a client-supplied role.
    assert not access.check("POST", "/approve/r1", USER_KEY).allowed


def test_log_only_mode_serves_but_flags(monkeypatch, caplog):
    monkeypatch.setenv("PREFECTOS_ENFORCE_ROLES", "0")
    with caplog.at_level("WARNING", logger="prefectos.access"):
        d = access.check("POST", "/approve/r1", USER_KEY)
    assert not d.allowed and not d.blocked
    assert "log-only" in caplog.text


# ── Framework hooks ─────────────────────────────────────────────────────────

def test_flask_guard():
    flask = pytest.importorskip("flask")
    app = flask.Flask("t")

    @app.route("/approve/<rid>", methods=["POST"])
    def approve(rid):
        return {"ok": True}

    @app.route("/runs")
    def runs():
        return {"ok": True}

    access.install_flask(app)
    c = app.test_client()
    assert c.post("/approve/r1", headers={"X-API-Key": USER_KEY}).status_code == 403
    assert c.post("/approve/r1").status_code == 403
    assert c.post("/approve/r1", headers={"X-API-Key": EXPIRED_KEY}).status_code == 403
    assert c.post("/approve/r1", headers={"X-API-Key": APPROVER_KEY}).status_code == 200
    assert c.get("/runs", headers={"X-API-Key": USER_KEY}).status_code == 200
    assert c.options("/approve/r1").status_code != 403          # CORS preflight untouched
    body = c.post("/approve/r1", headers={"X-API-Key": USER_KEY}).get_json()
    assert "Approve / reject gates" in body["detail"]


def test_fastapi_guard():
    pytest.importorskip("httpx")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()

    @app.post("/governance/freeze")
    def freeze():
        return {"ok": True}

    @app.get("/governance/packs")
    def packs():
        return {"ok": True}

    access.install_fastapi(app)
    c = TestClient(app)
    assert c.post("/governance/freeze", headers={"X-API-Key": USER_KEY}).status_code == 403
    assert c.post("/governance/freeze", headers={"X-API-Key": APPROVER_KEY}).status_code == 200
    assert c.get("/governance/packs", headers={"X-API-Key": USER_KEY}).status_code == 200
