"""A very small PDF writer — text, rules and shaded bands, nothing else.

The demo kit has to produce PDFs that `loan_extractors.read_pdf` (pdfplumber)
can lay out into rows and cells, and no PDF library is in requirements.txt.
Rather than add one for sample data, this writes the handful of operators that
matter: positioned text, a stroked line, a filled rectangle. Base-14 Helvetica
only, so no font is embedded and the file stays a few kilobytes.

Coordinates are given from the TOP of the page, because that is how the
documents read; the y-flip to PDF user space happens in `_stream`.
"""

from __future__ import annotations

from pathlib import Path

# Helvetica advance widths (1/1000 em) for the ASCII range the kit uses.
# Right-aligning a money column needs a real width, not a guess.
_W = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667,
    "'": 191, "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333,
    ".": 278, "/": 278, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584,
    "?": 556, "@": 1015, "[": 333, "\\": 278, "]": 333, "^": 469, "_": 556,
    "`": 333, "{": 334, "|": 260, "}": 334, "~": 584,
    "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722,
    "O": 778, "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722,
    "V": 667, "W": 944, "X": 667, "Y": 667, "Z": 611,
    "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556,
    "o": 556, "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556,
    "v": 500, "w": 722, "x": 500, "y": 500, "z": 500,
}
_DIGIT = 556

PAGE_W, PAGE_H = 595.0, 842.0     # A4 in points


def text_width(s: str, size: float) -> float:
    return sum(_DIGIT if c.isdigit() else _W.get(c, 556) for c in s) * size / 1000.0


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class Page:
    """One page. `y` is measured downwards from the top edge."""

    def __init__(self) -> None:
        self.ops: list[str] = []

    # ── text ────────────────────────────────────────────────────────────────
    def text(self, x: float, y: float, s: str, size: float = 9.0,
             bold: bool = False, gray: float | None = None) -> float:
        """Draw `s` with its left edge at `x`. Returns the right edge."""
        if not s:
            return x
        font = "/F2" if bold else "/F1"
        colour = f"{gray:.2f} {gray:.2f} {gray:.2f} rg\n" if gray is not None else ""
        reset = "0 0 0 rg\n" if gray is not None else ""
        self.ops.append(
            f"{colour}BT {font} {size:g} Tf 1 0 0 1 {x:.2f} {PAGE_H - y:.2f} Tm "
            f"({_esc(s)}) Tj ET\n{reset}"
        )
        return x + text_width(s, size)

    def right(self, x_right: float, y: float, s: str, size: float = 9.0,
              bold: bool = False, gray: float | None = None) -> float:
        """Draw `s` with its RIGHT edge at `x_right`. Returns the left edge."""
        x = x_right - text_width(s, size)
        self.text(x, y, s, size, bold, gray)
        return x

    def centre(self, x_mid: float, y: float, s: str, size: float = 9.0,
               bold: bool = False, gray: float | None = None) -> None:
        self.text(x_mid - text_width(s, size) / 2.0, y, s, size, bold, gray)

    # ── graphics ────────────────────────────────────────────────────────────
    def rule(self, x0: float, y: float, x1: float, width: float = 0.5,
             gray: float = 0.75) -> None:
        self.ops.append(
            f"{gray:.2f} G {width:g} w {x0:.2f} {PAGE_H - y:.2f} m "
            f"{x1:.2f} {PAGE_H - y:.2f} l S\n"
        )

    def band(self, x0: float, y: float, x1: float, height: float,
             rgb: tuple[float, float, float] = (0.91, 0.93, 0.97)) -> None:
        r, g, b = rgb
        self.ops.append(
            f"{r:.3f} {g:.3f} {b:.3f} rg {x0:.2f} {PAGE_H - y - height:.2f} "
            f"{x1 - x0:.2f} {height:.2f} re f 0 0 0 rg\n"
        )

    def _stream(self) -> bytes:
        return "".join(self.ops).encode("latin-1", "replace")


class Pdf:
    def __init__(self) -> None:
        self.pages: list[Page] = []

    def page(self) -> Page:
        p = Page()
        self.pages.append(p)
        return p

    def save(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        objects: list[bytes] = []          # 1-indexed on write

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        # 1 catalog, 2 page tree, 3/4 fonts, then page + content per page.
        add(b"<< /Type /Catalog /Pages 2 0 R >>")
        add(b"")                            # page tree, filled in below
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>")
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>")

        kids: list[int] = []
        for page in self.pages:
            stream = page._stream()
            content_id = add(b"<< /Length %d >>\nstream\n" % len(stream)
                             + stream + b"\nendstream")
            page_id = add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                b"/Contents %d 0 R >>" % (int(PAGE_W), int(PAGE_H), content_id)
            )
            kids.append(page_id)
        objects[1] = (b"<< /Type /Pages /Count %d /Kids [%s] >>"
                      % (len(kids), b" ".join(b"%d 0 R" % k for k in kids)))

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n" % (len(objects) + 1)
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += b"%010d 00000 n \n" % off
        out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objects) + 1, xref))
        path.write_bytes(bytes(out))
        return path
