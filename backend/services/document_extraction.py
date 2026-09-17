"""Text extraction from uploaded medical reports (derived artifact only).

- PDF: the embedded text layer via pypdf. Pages with too little text (scanned
  pages) fall back to OCR when the optional OCR stack is installed.
- PNG/JPEG: OCR (optional stack: rapidocr-onnxruntime; pypdfium2 renders
  scanned PDF pages).

The original bytes are only read, never modified. Nothing here logs document
content; errors carry short codes only.
"""
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)
# pypdf reports structural problems through its own logger; keep that quiet (codes are recorded instead).
logging.getLogger("pypdf").setLevel(logging.ERROR)

MAX_PAGES = 50
MIN_PAGE_TEXT_CHARS = 40   # below this a PDF page is treated as scanned
OCR_RENDER_SCALE = 2.0     # ~144 dpi


class ExtractionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class ExtractionResult:
    text: str
    method: str                 # pdf_text | ocr | pdf_text+ocr
    quality: str                # good | low
    page_count: int
    warnings: List[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)


def detect_format(data: bytes) -> Optional[str]:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    return None


_ocr_engine = None
_ocr_checked = False


def ocr_available() -> bool:
    global _ocr_checked, _ocr_engine
    if not _ocr_checked:
        _ocr_checked = True
        try:
            import rapidocr_onnxruntime  # noqa: F401
            import pypdfium2  # noqa: F401
            _ocr_engine = "rapidocr"
        except Exception:
            _ocr_engine = None
    return _ocr_engine is not None


_engine_instance = None


def _engine():
    global _engine_instance
    if _engine_instance is None:
        from rapidocr_onnxruntime import RapidOCR
        _engine_instance = RapidOCR()
    return _engine_instance


def _ocr_image(image) -> str:
    """OCR a PIL image; returns text lines rebuilt in reading order."""
    import numpy as np
    result, _ = _engine()(np.asarray(image.convert("RGB")))
    if not result:
        return ""
    boxes = []
    for box, text, _score in result:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        boxes.append((sum(ys) / len(ys), min(xs), max(ys) - min(ys), text))
    boxes.sort()
    lines, current, current_y, current_h = [], [], None, None
    for y, x, h, text in boxes:
        if current_y is not None and abs(y - current_y) > max(current_h, h) * 0.6:
            lines.append("  ".join(t for _, t in sorted(current)))
            current = []
        if not current:
            current_y, current_h = y, h
        current.append((x, text))
    if current:
        lines.append("  ".join(t for _, t in sorted(current)))
    return "\n".join(lines)


def _pdf_extract(data: bytes, result_timings: dict, on_ocr_start: Optional[Callable[[], None]]) -> ExtractionResult:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    t0 = time.perf_counter()
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("pdf_encrypted")
        pages = list(reader.pages)
    except ExtractionError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError):
        raise ExtractionError("pdf_unreadable") from None
    except Exception:
        raise ExtractionError("pdf_unreadable") from None
    if not pages:
        raise ExtractionError("pdf_empty")
    warnings = []
    if len(pages) > MAX_PAGES:
        warnings.append(f"Only the first {MAX_PAGES} pages were processed.")
        pages = pages[:MAX_PAGES]

    texts: List[Optional[str]] = []
    for page in pages:
        try:
            texts.append((page.extract_text() or "").strip())
        except Exception:
            texts.append("")
    result_timings["pdf_text_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    scanned = [i for i, t in enumerate(texts) if len(t) < MIN_PAGE_TEXT_CHARS]
    method = "pdf_text"
    if scanned:
        if ocr_available():
            if on_ocr_start:
                on_ocr_start()
            t1 = time.perf_counter()
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(data)
            try:
                for i in scanned:
                    image = doc[i].render(scale=OCR_RENDER_SCALE).to_pil()
                    texts[i] = _ocr_image(image).strip()
            finally:
                doc.close()
            result_timings["ocr_ms"] = round((time.perf_counter() - t1) * 1000, 1)
            method = "ocr" if len(scanned) == len(texts) else "pdf_text+ocr"
            warnings.append(f"{len(scanned)} page(s) were read with OCR; check values carefully.")
        else:
            warnings.append(f"{len(scanned)} page(s) have no text layer and OCR is not available on this server.")

    body = "\n\n".join(f"--- Page {i + 1} ---\n{t}" for i, t in enumerate(texts))
    if not any(texts):
        raise ExtractionError("no_text_found" if ocr_available() or not scanned else "ocr_unavailable")
    quality = "low" if method != "pdf_text" or scanned else "good"
    return ExtractionResult(text=body, method=method, quality=quality, page_count=len(texts),
                            warnings=warnings, timings=result_timings)


def _image_extract(data: bytes, timings: dict, on_ocr_start: Optional[Callable[[], None]]) -> ExtractionResult:
    if not ocr_available():
        raise ExtractionError("ocr_unavailable")
    from PIL import Image, UnidentifiedImageError
    if on_ocr_start:
        on_ocr_start()
    t0 = time.perf_counter()
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ExtractionError("image_unreadable") from None
    text = _ocr_image(image).strip()
    timings["ocr_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if not text:
        raise ExtractionError("no_text_found")
    return ExtractionResult(text=f"--- Page 1 ---\n{text}", method="ocr", quality="low", page_count=1,
                            warnings=["The document was read with OCR; check values carefully."],
                            timings=timings)


def extract_text(data: bytes, on_ocr_start: Optional[Callable[[], None]] = None) -> ExtractionResult:
    """Extract text; ``on_ocr_start`` is called before OCR runs (OCR is used only when needed)."""
    fmt = detect_format(data)
    timings: dict = {}
    started = time.perf_counter()
    if fmt == "pdf":
        result = _pdf_extract(data, timings, on_ocr_start)
    elif fmt in ("png", "jpeg"):
        result = _image_extract(data, timings, on_ocr_start)
    else:
        raise ExtractionError("unsupported_format")
    result.timings["extraction_total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    logger.info("Report text extracted: method=%s pages=%d chars=%d",
                result.method, result.page_count, len(result.text))
    return result
