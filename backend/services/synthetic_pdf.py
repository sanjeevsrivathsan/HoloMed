"""Minimal PDF writer for clearly labelled synthetic demo and test documents.

Produces PDFs with a real text layer (Helvetica), so synthetic reports go through
exactly the same extraction pipeline as uploaded ones.
"""
from typing import List

LINES_PER_PAGE = 48


def _escape(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(lines: List[str], font_size: int) -> bytes:
    leading = font_size + 5
    ops = ["BT", f"/F1 {font_size} Tf", f"{leading} TL", "50 800 Td"]
    for i, line in enumerate(lines[:LINES_PER_PAGE]):
        ops.append(f"({_escape(line)}) Tj" if i == 0 else f"T* ({_escape(line)}) Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def text_pdf_pages(pages: List[List[str]], font_size: int = 10) -> bytes:
    """One PDF page per list of lines (at most 48 lines per page)."""
    n = len(pages)
    font_obj = 3 + 2 * n
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + " ".join(f"{3 + 2 * i} 0 R" for i in range(n)).encode()
        + b"] /Count " + str(n).encode() + b" >>",
    ]
    for i, lines in enumerate(pages):
        stream = _page_stream(lines, font_size)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                       b"/Resources << /Font << /F1 " + str(font_obj).encode() + b" 0 R >> >> /Contents "
                       + str(4 + 2 * i).encode() + b" 0 R >>")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def text_pdf(lines: List[str], font_size: int = 10) -> bytes:
    """Single-page PDF (lines beyond the first 48 are dropped)."""
    return text_pdf_pages([lines], font_size)
