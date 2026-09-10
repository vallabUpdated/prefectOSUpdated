# Part of the PrefectOS core package — email intake validation layer.
"""Three-stage validation for emailed documents.

Stage 1 — sender validity: RFC-style address syntax + SPF/DKIM/DMARC
verdicts parsed from Authentication-Results (anti-spoofing: the
allowlist alone trusts the From: header, which anyone can forge).

Stage 2 — content vs predefined templates: PDF structural check, text
extraction (pdfplumber → pypdf → dependency-free literal scan), and
classification against doc_templates.json.

Stage 3 — valid document set: per product, the classified attachments
must form the complete required pack; incomplete packs are rejected
with the exact missing list.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

# ── Stage 1: sender validity ───────────────────────────────────────────
_EMAIL_SYNTAX = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.\-]{1,64}"
    r"@[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)+$"
)
_AUTH_RE = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z0-9]+)", re.I)


def is_valid_address_syntax(addr: str) -> bool:
    addr = (addr or "").strip()
    return bool(addr) and len(addr) <= 254 and bool(_EMAIL_SYNTAX.match(addr)) \
        and ".." not in addr


def parse_authentication_results(msg: EmailMessage) -> dict[str, str]:
    """Collect spf/dkim/dmarc verdicts from Authentication-Results headers
    (stamped by the receiving server — Gmail/Workspace always adds them)."""
    verdicts: dict[str, str] = {}
    for header in msg.get_all("Authentication-Results", []) or []:
        for mech, result in _AUTH_RE.findall(str(header)):
            verdicts.setdefault(mech.lower(), result.lower())
    return verdicts


def validate_sender_authenticity(msg: EmailMessage, addr: str,
                                 require_auth: bool = True) -> tuple[bool, str]:
    if not is_valid_address_syntax(addr):
        return False, "invalid_address_syntax"
    if not require_auth:
        return True, "ok"
    v = parse_authentication_results(msg)
    if not v:
        return False, "no_authentication_results"
    if v.get("dmarc") == "pass" or v.get("dkim") == "pass" or v.get("spf") == "pass":
        return True, "ok"
    return False, "sender_auth_failed:" + ",".join(
        f"{k}={val}" for k, val in sorted(v.items()))


# ── PDF text extraction ────────────────────────────────────────────────
_PDF_MAGIC = b"%PDF-"
_LITERAL_TEXT = re.compile(rb"\(((?:[^()\\]|\\.)*)\)\s*(?:Tj|'|\")")


def looks_like_pdf(payload: bytes) -> bool:
    return payload[:1024].lstrip().startswith(_PDF_MAGIC)


def extract_pdf_text(payload: bytes, engine: str = "auto") -> tuple[str, str]:
    """Returns (text, engine_used). Empty text = scanned/image-only PDF."""
    if engine in ("auto", "pdfplumber"):
        try:
            import io, pdfplumber                       # noqa: E401
            with pdfplumber.open(io.BytesIO(payload)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            return text, "pdfplumber"
        except Exception:
            if engine == "pdfplumber":
                return "", "pdfplumber_failed"
    if engine in ("auto", "pypdf"):
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(payload))
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
            return text, "pypdf"
        except Exception:
            if engine == "pypdf":
                return "", "pypdf_failed"
    chunks = [m.group(1).decode("latin-1", "replace")
              for m in _LITERAL_TEXT.finditer(payload)]
    return " ".join(chunks), "literal_scan"


def count_pdf_pages(payload: bytes) -> int:
    return max(1, payload.count(b"/Type /Page") + payload.count(b"/Type/Page")
               - payload.count(b"/Type /Pages") - payload.count(b"/Type/Pages"))


# ── Stage 2: template classification ───────────────────────────────────
@dataclass
class DocTemplate:
    doc_type: str
    label: str
    required_keywords: list[str] = field(default_factory=list)  # ALL must appear
    any_keywords: list[str] = field(default_factory=list)       # ≥ min_any appear
    min_any: int = 1
    min_pages: int = 1
    max_pages: int = 200

    def matches(self, text: str, pages: int) -> tuple[bool, str]:
        low = text.lower()
        missing = [k for k in self.required_keywords if k.lower() not in low]
        if missing:
            return False, "missing_keywords:" + ",".join(missing[:5])
        if self.any_keywords:
            hits = sum(1 for k in self.any_keywords if k.lower() in low)
            if hits < self.min_any:
                return False, f"insufficient_markers:{hits}/{self.min_any}"
        if not (self.min_pages <= pages <= self.max_pages):
            return False, f"page_count_out_of_range:{pages}"
        return True, "ok"


@dataclass
class ClassifiedDoc:
    filename: str
    doc_type: str | None          # None => no template matched
    detail: str
    engine: str


class DocumentValidator:
    """Loads doc_templates.json: templates + per-product required sets."""

    def __init__(self, templates: list[DocTemplate],
                 document_sets: dict[str, list[str]]):
        self.templates = templates
        self.document_sets = document_sets

    @classmethod
    def load(cls, path: str | Path) -> "DocumentValidator":
        raw = json.loads(Path(path).read_text())
        templates = [DocTemplate(**t) for t in raw.get("templates", [])]
        return cls(templates, raw.get("document_sets", {}))

    def classify(self, filename: str, payload: bytes,
                 engine: str = "auto") -> ClassifiedDoc:
        if not looks_like_pdf(payload):
            return ClassifiedDoc(filename, None, "not_a_pdf", "none")
        text, used = extract_pdf_text(payload, engine)
        if not text.strip():
            return ClassifiedDoc(filename, None, "no_extractable_text", used)
        pages = count_pdf_pages(payload)
        reasons = []
        for t in self.templates:
            ok, why = t.matches(text, pages)
            if ok:
                return ClassifiedDoc(filename, t.doc_type, "matched", used)
            reasons.append(f"{t.doc_type}({why})")
        return ClassifiedDoc(filename, None,
                             "template_mismatch:" + ";".join(reasons[:4]), used)

    def check_set(self, product: str,
                  docs: list) -> tuple[bool, list[str]]:
        """(complete?, missing doc_types). Unknown product => no set rule."""
        required = self.document_sets.get(product)
        if not required:
            return True, []
        present = {d.doc_type for d in docs if d.doc_type}
        missing = [r for r in required if r not in present]
        return not missing, missing
