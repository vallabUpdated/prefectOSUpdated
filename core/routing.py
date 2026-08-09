# PrefectOS core — role-based model routing.
"""Role -> (model, endpoint, tier) resolution for the batch data plane.

Existing agents keep using WORKER_MODEL / SUPERVISOR_MODEL from config.py —
nothing changes for them. Pooled agents name a ROLE; this module decides
which model and endpoint serve it, so swapping the vLLM pool in for the
Anthropic API is an environment change, not a code change.

Environment (all optional; sensible fallbacks to existing config):
  ROUTE_RESOLVER_MODEL     e.g. "qwen3.5-9b-awq" as known to the LiteLLM proxy
  ROUTE_RESOLVER_BASE_URL  e.g. "http://litellm:4000"   (empty = Anthropic API)
  ROUTE_CLASSIFIER_MODEL / ROUTE_CLASSIFIER_BASE_URL
  ROUTE_SUPERVISOR_MODEL / ROUTE_SUPERVISOR_BASE_URL
  ROUTE_API_KEY            key sent to the proxy (falls back to ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .config import WORKER_MODEL, SUPERVISOR_MODEL


@dataclass(frozen=True)
class RouteConfig:
    role: str
    model: str
    base_url: str          # "" -> default Anthropic endpoint
    api_key: str | None    # None -> SDK default (ANTHROPIC_API_KEY)

    provider: str = "anthropic"     # anthropic | bedrock | proxy

    @property
    def tier(self) -> str:
        if self.provider == "bedrock":
            return "bedrock"
        return "self-hosted" if self.base_url else "anthropic"


_ROLE_DEFAULT_MODEL = {
    "resolver":   WORKER_MODEL,       # small/fast: exception adjudication
    "classifier": WORKER_MODEL,       # small/fast: batch doc-type routing
    "supervisor": SUPERVISOR_MODEL,   # large: comprehension, planning
}


def resolve_role(role: str) -> RouteConfig:
    key = role.upper()
    model = os.getenv(f"ROUTE_{key}_MODEL",
                      _ROLE_DEFAULT_MODEL.get(role, WORKER_MODEL))
    base_url = os.getenv(f"ROUTE_{key}_BASE_URL", "")
    api_key = os.getenv("ROUTE_API_KEY") or None
    provider = os.getenv(f"ROUTE_{key}_PROVIDER",
                         os.getenv("ROUTE_PROVIDER",
                                   os.getenv("PREFECTOS_LLM_PROVIDER", "anthropic"))).lower()
    return RouteConfig(role=role, model=model, base_url=base_url,
                       api_key=api_key, provider=provider)
