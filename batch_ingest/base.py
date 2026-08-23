"""Adapter contract + errors for the external analyzer tier."""
from __future__ import annotations

import abc
import hashlib
import json
from pathlib import Path


class AdapterError(RuntimeError):
    """Vendor call failed in a mapped, non-crashing way (timeout, 4xx/5xx,
    schema drift). Carries enough context for the ledger."""
    def __init__(self, vendor: str, reason: str, detail: str = ""):
        super().__init__(f"{vendor}: {reason} {detail}".strip())
        self.vendor, self.reason, self.detail = vendor, reason, detail


class EgressForbidden(RuntimeError):
    """Raised when routing policy forbids sending this client's documents to
    any external vendor. Must always be ledgered by the caller."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_obj(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


class BaseAnalyzer(abc.ABC):
    """Contract every external adapter implements. analyze() must return a
    dict in the canonical schema (docs/canonical_schema.md) with a
    provenance block, or raise AdapterError. Never partial silent output."""

    vendor_name: str = "base"
    cost_per_call_estimate_inr: float = 0.0

    @abc.abstractmethod
    def analyze(self, file_path: str, doc_type: str = "bank_statement") -> dict: ...

    def health(self) -> bool:
        """Cheap liveness check; adapters may override."""
        return True
