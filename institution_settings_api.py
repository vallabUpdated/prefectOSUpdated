"""Institution settings, shared across the app and the marketing site.

GET/PUT /institution-settings, authenticated with the same admin-issued
API keys the sign-in dialog accepts (X-API-Key header). Values persist to
a JSON file so every surface — workspace ⚙ dialog, in-app landing page,
and the public site's Settings section — reads and writes one record.

Key validation: the PREFECTOS_API_KEYS env var (comma-separated) when
set; otherwise the demo key set that ships with the product. Demo-grade
by design — production key management belongs in the gateway/SSO.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

_STORE = Path(os.environ.get("PREFECTOS_SETTINGS_PATH", "project_output/institution_settings.json"))

_DEMO_KEYS = {
    "prf_live_admin_8849":       {"name": "Sarah Jenkins",  "role": "System Admin"},
    "prf_live_underwriter_9921": {"name": "David Vance",    "role": "Lead Underwriter"},
    "prf_live_risk_3342":        {"name": "Elena Rostova",  "role": "Risk Officer"},
    "prf_live_auditor_1105":     {"name": "Marcus Vance",   "role": "Internal Auditor"},
}

DEFAULTS = {"bankName": "", "fxRate": 88.0, "policyPath": ""}


def _identity_for(key: str | None) -> dict:
    if not key or len(key.strip()) < 6:
        raise HTTPException(401, "A valid API key is required (X-API-Key header).")
    key = key.strip()
    env_keys = [k.strip() for k in os.environ.get("PREFECTOS_API_KEYS", "").split(",") if k.strip()]
    if env_keys:
        if key not in env_keys:
            raise HTTPException(401, "Unknown API key.")
        return {"name": "Licensee", "role": "Licensee"}
    if key in _DEMO_KEYS:
        return _DEMO_KEYS[key]
    # demo mode mirrors the sign-in dialog: any plausible key is a licensee
    return {"name": "Enterprise Licensee", "role": "Licensee"}


def _read() -> dict:
    try:
        data = json.loads(_STORE.read_text())
        return {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
    except Exception:
        return dict(DEFAULTS)


class SettingsBody(BaseModel):
    bankName: str = Field("", max_length=120)
    fxRate: float = Field(88.0, gt=0)
    policyPath: str = Field("", max_length=400)


@router.get("/institution-settings")
def get_settings(x_api_key: str | None = Header(default=None)):
    who = _identity_for(x_api_key)
    return {"settings": _read(), "authenticated_as": who}


@router.put("/institution-settings")
def put_settings(body: SettingsBody, x_api_key: str | None = Header(default=None)):
    who = _identity_for(x_api_key)
    data = {"bankName": body.bankName, "fxRate": body.fxRate, "policyPath": body.policyPath}
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    _STORE.write_text(json.dumps(data, indent=2))
    return {"settings": data, "authenticated_as": who, "saved": True}
