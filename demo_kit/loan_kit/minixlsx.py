"""A very small .xlsx writer — one sheet of typed cells, nothing else.

The kit ships an Excel twin of every document, and the project has no
spreadsheet dependency it could borrow for the *build* step (openpyxl and
pandas are runtime requirements for reading Excel, not for generating the
samples). An .xlsx is a zip of a few XML parts, so this writes them directly:
inline strings, numbers with a money format, bold headers, column widths.

Same intent as `minipdf.py` — the kit regenerates on a bare Python.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path

# Style indices into the cellXfs table written by `_STYLES` below.
PLAIN, BOLD, MONEY, MONEY_BOLD = 0, 1, 2, 3


@dataclass
class Cell:
    value: object
    style: int = PLAIN
    numeric: bool = False


def b(value) -> Cell:
    """A bold text cell — section headings and column headers."""
    return Cell(value, BOLD)


def m(value, bold: bool = False) -> Cell:
    """A money cell: a real number, formatted #,##0.00 in Excel."""
    return Cell(float(value), MONEY_BOLD if bold else MONEY, numeric=True)


def n(value, bold: bool = False) -> Cell:
    """A plain number — row counters, tenures, counts."""
    return Cell(value, BOLD if bold else PLAIN, numeric=True)


def _esc(text: str) -> str:
    out = (str(text).replace("&", "&amp;").replace("<", "&lt;")
           .replace(">", "&gt;"))
    # Excel rejects most control characters outright.
    return "".join(ch for ch in out if ch >= " " or ch in "\t\n")


def _col_name(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


class Sheet:
    def __init__(self, name: str = "Sheet1",
                 widths: list[float] | None = None) -> None:
        self.name = name
        self.widths = widths or []
        self.rows: list[list] = []

    def row(self, *cells) -> None:
        """One row. Bare values are plain cells; wrap with b()/m()/n()."""
        self.rows.append(list(cells))

    def blank(self) -> None:
        self.rows.append([])

    def _xml(self) -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<worksheet xmlns="http://schemas.openxmlformats.org/'
            'spreadsheetml/2006/main">',
        ]
        if self.widths:
            parts.append("<cols>")
            for i, width in enumerate(self.widths, start=1):
                parts.append(f'<col min="{i}" max="{i}" width="{width:g}" '
                             f'customWidth="1"/>')
            parts.append("</cols>")
        parts.append("<sheetData>")

        for r, cells in enumerate(self.rows, start=1):
            if not cells:
                parts.append(f'<row r="{r}"/>')
                continue
            parts.append(f'<row r="{r}">')
            for c, raw in enumerate(cells):
                if raw is None or raw == "":
                    continue
                cell = raw if isinstance(raw, Cell) else Cell(raw)
                ref = f"{_col_name(c)}{r}"
                style = f' s="{cell.style}"' if cell.style else ""
                if cell.numeric or isinstance(cell.value, (int, float)):
                    parts.append(f'<c r="{ref}"{style}><v>{cell.value}</v></c>')
                else:
                    parts.append(f'<c r="{ref}"{style} t="inlineStr">'
                                 f'<is><t xml:space="preserve">'
                                 f'{_esc(cell.value)}</t></is></c>')
            parts.append("</row>")

        parts.append("</sheetData></worksheet>")
        return "".join(parts)


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">'
    '<Default Extension="rels" ContentType="application/'
    'vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)

_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/officeDocument" Target="xl/'
    'workbook.xml"/>'
    "</Relationships>"
)

_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/worksheet" Target="worksheets/'
    'sheet1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/'
    'officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    "</Relationships>"
)

_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/'
    'main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.00"/>'
    "</numFmts>"
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    "</fonts>"
    '<fills count="2"><fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
    'borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" '
    'applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" '
    'applyNumberFormat="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" '
    'applyNumberFormat="1" applyFont="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/>'
    "</cellStyles>"
    "</styleSheet>"
)


def save(sheet: Sheet, path: Path) -> Path:
    """Write a single-sheet workbook to `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/'
        '2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
        '2006/relationships">'
        f'<sheets><sheet name="{_esc(sheet.name)[:31]}" sheetId="1" '
        'r:id="rId1"/></sheets>'
        "</workbook>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet._xml())
    return path
