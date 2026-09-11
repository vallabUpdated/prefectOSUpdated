"""Render the application-stage packs (application_docs.py) into the kit.

    bundles/<pack>/NN_*.pdf          via minipdf  (no dependencies)
    bundles_excel/<pack>/NN_*.xlsx   via minixlsx (same content, one sheet)
    bundles/<pack>/README.txt        expected decision and why

Called from build_kit.main(); can also run alone:
    python demo_kit/loan_kit/application_kit.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

from minipdf import Pdf, Page, PAGE_H            # noqa: E402
from minixlsx import Sheet, b, m, save           # noqa: E402
import application_docs as docs                  # noqa: E402

LEFT, RIGHT, VALUE_COL = 56.0, 539.0, 360.0
MONEY = re.compile(r"^-?\d{1,3}(?:,\d{3})*\.\d{2}$")


# ── PDF ──────────────────────────────────────────────────────────────────
def _pdf_page(pdf: Pdf, title: str, lines: list[str]) -> None:
    p: Page = pdf.page()
    p.band(LEFT, 48, RIGHT, 34)
    p.text(LEFT + 10, 70, title[:70], 11.5, bold=True)
    p.text(LEFT, 98, docs.STAMP, 7, gray=0.45)
    y = 124.0
    for ln in lines:
        if y > PAGE_H - 60:                      # overflow: continue on a new page
            p = pdf.page()
            p.text(LEFT, 60, title[:70] + " (contd.)", 9, bold=True, gray=0.3)
            y = 84.0
        if ln == "":
            y += 7; continue
        if ln.startswith("## "):
            p.band(LEFT, y - 11, RIGHT, 16)
            p.text(LEFT + 6, y, ln[3:], 9, bold=True)
            y += 20; continue
        if ln.startswith("@@"):
            label, value = ln[2:].split("|", 1)
            p.text(LEFT, y, label, 9)
            p.right(VALUE_COL, y, value, 9, bold=bool(MONEY.match(value)))
            y += 15; continue
        size = 8.5 if len(ln) > 95 else 9
        p.text(LEFT, y, ln, size)
        y += 14
    p.rule(LEFT, 790, RIGHT, 0.5, 0.8)
    p.text(LEFT, 802, docs.STAMP, 7, gray=0.45)


def write_pdf(path: Path, pages) -> None:
    pdf = Pdf()
    for title, lines in pages:
        _pdf_page(pdf, title, lines)
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)


# ── Excel ────────────────────────────────────────────────────────────────
def write_xlsx(path: Path, pages) -> None:
    """The same document as one sheet: each page's title as a bold heading,
    '@@' rows as Label | Value (money as real numbers), text lines as-is."""
    s = Sheet(path.stem[:31], widths=[42, 26, 60])
    for i, (title, lines) in enumerate(pages):
        if i:
            s.blank()
        s.row(b(title))
        s.row(docs.STAMP)
        for ln in lines:
            if ln == "":
                s.blank()
            elif ln.startswith("## "):
                s.row(b(ln[3:]))
            elif ln.startswith("@@"):
                label, value = ln[2:].split("|", 1)
                s.row(label, m(value.replace(",", "")) if MONEY.match(value) else value)
            else:
                s.row(ln)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(s, path)


# ── bundles ──────────────────────────────────────────────────────────────
def build(bundles: Path, bundles_xl: Path | None = None) -> dict[str, dict]:
    built = {}
    for pack, (product, fn) in docs.PACK_SPECS.items():
        applicant, documents, expect = fn()
        folder = bundles / pack
        folder.mkdir(parents=True, exist_ok=True)
        for name, pages in documents.items():
            write_pdf(folder / name, pages)
            if bundles_xl is not None:
                write_xlsx(bundles_xl / pack / (Path(name).stem + ".xlsx"), pages)
        (folder / "README.txt").write_text(
            f"{pack}\nApplicant: {applicant.name} (fictional)   Product: {product}\n"
            f"Expected decision: {expect[0]}\n" + "".join(f"  - {x}\n" for x in expect[1:]),
            encoding="utf-8")
        if bundles_xl is not None:
            write_xlsx(bundles_xl / pack / "README.xlsx",
                       [("README - " + pack, [f"Applicant: {applicant.name} (fictional)",
                                               f"Product: {product}", "",
                                               f"## Expected decision: {expect[0]}",
                                               *(f"  - {x}" for x in expect[1:])])])
        built[pack] = {"product": product, "applicant": applicant,
                       "docs": list(documents), "expect": expect}
    return built


if __name__ == "__main__":
    out = build(KIT / "bundles", KIT / "bundles_excel")
    for pack, info in out.items():
        print(f"  {pack:<36} {info['applicant'].name:<16} {len(info['docs'])} docs  -> {info['expect'][0]}")
