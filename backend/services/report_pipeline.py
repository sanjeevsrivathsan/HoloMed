"""Report ingestion lifecycle.

    processing:  uploaded → processing → processed | failed (retry allowed)
    review:      needs_review → partially_confirmed → confirmed
                 (the report date and every value are confirmed or ignored by the user)

The stored ``status`` combines both (extracted / needs_review / partially_confirmed /
confirmed while processed); API responses expose them separately.

The original upload is stored once and never changed. Extraction output
(text, measurement candidates) lives in derived tables; canonical
MedicalMeasurement rows are only created when the user confirms values.
Legacy reports with status "ready" (created before this pipeline) are shown
as completed.
"""
import json
import logging
import time
import traceback
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, delete, select

from ..models import ExtractedMeasurement, MedicalMeasurement, Report, ReportExtraction, ReportSummary, \
    SourceReference
from ..routers.medical_data import log_action
from . import document_extraction, lab_parser
from .storage import retrieve_file

logger = logging.getLogger(__name__)

UPLOADED = "uploaded"
PROCESSING = "processing"
EXTRACTED = "extracted"
NEEDS_REVIEW = "needs_review"
PARTIALLY_CONFIRMED = "partially_confirmed"
CONFIRMED = "confirmed"
COMPLETED = "completed"          # legacy: summary generated (no longer set)
FAILED = "failed"
LEGACY_READY = "ready"

# Processing stages recorded on ReportExtraction.stage
STAGE_UPLOAD = "upload"
STAGE_TEXT = "text_extraction"
STAGE_OCR = "ocr"
STAGE_STRUCTURED = "structured_extraction"
STAGE_SAVE = "save"
STAGE_DONE = "done"

STALE_PROCESSING = timedelta(minutes=10)

# Document classification offered at upload. Legacy values stay accepted.
DOCUMENT_TYPES = [
    ("Blood Test", "Blood Test / Laboratory Report"),
    ("Imaging Report", "Radiology Report"),
    ("Discharge Summary", "Discharge Summary"),
    ("Clinical Note", "Clinical Note"),
    ("Prescription", "Prescription"),
    ("Other", "Other"),
]
LEGACY_TYPES = {"Pathology", "Consultation", "Operative Report"}
ALLOWED_TYPES = {t for t, _ in DOCUMENT_TYPES} | LEGACY_TYPES
LAB_TYPES = {"Blood Test", "Pathology"}

ERROR_MESSAGES = {
    "unsupported_format": "This file type is not supported.",
    "pdf_encrypted": "The PDF is password-protected. Upload an unprotected copy.",
    "pdf_unreadable": "The PDF could not be read. It may be damaged.",
    "pdf_empty": "The PDF has no pages.",
    "image_unreadable": "The image could not be read. It may be damaged.",
    "ocr_unavailable": "This document has no text layer and OCR is not installed on this server.",
    "no_text_found": "No readable text was found in the document.",
    "file_missing": "The stored original could not be found.",
    "interrupted": "Processing was interrupted. Retry to process the document again.",
    "structured_extraction_failed": ("The report text was extracted, but structured measurements could not be "
                                     "created. You can retry processing."),
    "persistence_failed": "The results could not be saved. You can retry processing.",
    "internal_error": "The document could not be processed. You can retry processing.",
}


def public_status(status: str) -> str:
    return COMPLETED if status == LEGACY_READY else status


def _now() -> datetime:
    return datetime.utcnow()


def get_extraction(session: Session, report_id: int) -> Optional[ReportExtraction]:
    return session.exec(select(ReportExtraction).where(ReportExtraction.report_id == report_id)).first()


def is_stale(extraction: Optional[ReportExtraction]) -> bool:
    return bool(extraction and extraction.status == PROCESSING
                and _now() - extraction.updated_at > STALE_PROCESSING)


def start(session: Session, report: Report) -> ReportExtraction:
    """Reset derived, unconfirmed artifacts and mark the report as processing."""
    extraction = get_extraction(session, report.id)
    if extraction is None:
        extraction = ReportExtraction(report_id=report.id, owner_id=report.owner_id)
    extraction.status = PROCESSING
    extraction.stage = STAGE_TEXT
    extraction.method = "none"
    extraction.error_code = None
    extraction.updated_at = _now()
    session.add(extraction)
    session.exec(delete(ExtractedMeasurement).where(
        ExtractedMeasurement.report_id == report.id,
        ExtractedMeasurement.measurement_id.is_(None)))  # confirmed candidates are kept
    report.status = PROCESSING
    session.add(report)
    session.commit()
    return extraction


def _log_crash(what: str, report_id: int, exc: BaseException) -> None:
    """Log an unexpected error with its stack frames but without the exception message,
    which may quote document content."""
    frames = "".join(traceback.format_tb(exc.__traceback__))
    logger.error("%s crashed report=%s error=%s\n%s", what, report_id, type(exc).__name__, frames)


def _set_stage(session: Session, extraction: ReportExtraction, stage: str, **fields) -> None:
    extraction.stage = stage
    for key, value in fields.items():
        setattr(extraction, key, value)
    extraction.updated_at = _now()
    session.add(extraction)
    session.commit()


def _fail(session: Session, report: Report, extraction: ReportExtraction, code: str, timings: dict,
          stage: Optional[str] = None):
    extraction.status = FAILED
    extraction.stage = stage or extraction.stage
    extraction.error_code = code
    extraction.timings = json.dumps(timings)
    extraction.updated_at = _now()
    report.status = FAILED
    session.add(extraction)
    session.add(report)
    log_action(session, report.owner_id, "report_extraction_failed",
               {"report_id": report.id, "error": code, "stage": extraction.stage})
    session.commit()
    logger.warning("Report processing failed report=%s stage=%s code=%s", report.id, extraction.stage, code)


def process(engine: Engine, report_id: int) -> None:
    """Run text extraction -> structured extraction -> save for one report (background task).

    Each stage is recorded on the extraction row so the UI can show real progress; a failure
    records the stage that failed. AI summaries are not part of ingestion.
    """
    started = time.perf_counter()

    def elapsed() -> float:
        return round((time.perf_counter() - started) * 1000, 1)

    with Session(engine) as session:
        report = session.get(Report, report_id)
        extraction = get_extraction(session, report_id)
        if report is None or extraction is None:
            return
        _set_stage(session, extraction, STAGE_TEXT)

        # 1. Text extraction (OCR fallback only for pages without a text layer)
        data = retrieve_file(report.storage_key, report.storage_provider)
        if not data:
            _fail(session, report, extraction, "file_missing", {}, STAGE_TEXT)
            return
        try:
            result = document_extraction.extract_text(
                data, on_ocr_start=lambda: _set_stage(session, extraction, STAGE_OCR, method="ocr"))
        except document_extraction.ExtractionError as exc:
            ocr_stage = exc.code == "ocr_unavailable" or extraction.stage == STAGE_OCR
            _fail(session, report, extraction, exc.code, {"total_ms": elapsed()},
                  STAGE_OCR if ocr_stage else STAGE_TEXT)
            return
        except Exception as exc:  # never leave a report stuck in "processing"
            _log_crash("Text extraction", report_id, exc)
            _fail(session, report, extraction, "internal_error", {"total_ms": elapsed()})
            return
        timings = dict(result.timings)
        # Keep the extracted text even if a later stage fails, so the user can still read it.
        _set_stage(session, extraction, STAGE_STRUCTURED, method=result.method, quality=result.quality,
                   page_count=result.page_count, char_count=len(result.text), text=result.text,
                   warnings=json.dumps(result.warnings))

        # 2. Structured extraction (deterministic parser)
        t_parse = time.perf_counter()
        try:
            parsed = lab_parser.parse_report_text(result.text, ocr=result.method != "pdf_text")
        except Exception as exc:
            _log_crash("Structured extraction", report_id, exc)
            timings["total_ms"] = elapsed()
            _fail(session, report, extraction, "structured_extraction_failed", timings, STAGE_STRUCTURED)
            return
        timings["parse_ms"] = round((time.perf_counter() - t_parse) * 1000, 1)
        _set_stage(session, extraction, STAGE_SAVE)

        # 3. Save candidates and results
        try:
            confirmed_keys = {
                (c.test_name.lower(), c.value_text) for c in session.exec(
                    select(ExtractedMeasurement).where(ExtractedMeasurement.report_id == report_id,
                                                       ExtractedMeasurement.measurement_id.is_not(None)))
            }
            added = 0
            for cand in parsed.candidates:
                if (cand.test_name.lower(), cand.value_text) in confirmed_keys:
                    continue
                session.add(ExtractedMeasurement(report_id=report_id, owner_id=report.owner_id, **vars(cand)))
                added += 1

            warnings = list(result.warnings)
            if report.type in LAB_TYPES or added:
                warnings += parsed.warnings
            extraction.status = "succeeded"
            extraction.stage = STAGE_DONE
            extraction.document_date = parsed.document_date
            extraction.date_candidates = json.dumps([vars(c) for c in parsed.date_candidates])
            extraction.warnings = json.dumps(warnings)
            timings["total_ms"] = elapsed()
            extraction.timings = json.dumps(timings)
            extraction.updated_at = _now()
            if not date_is_confirmed(report):
                report.detected_date = parsed.document_date
                if parsed.document_date:
                    # Provisional: shown as "detected, not confirmed" until the user confirms it.
                    report.report_date = parsed.document_date
                    report.date_source = "extracted"
                report.date_confirmed = False
            report.status = NEEDS_REVIEW if added else EXTRACTED
            session.add(extraction)
            session.add(report)
            log_action(session, report.owner_id, "report_extraction_completed",
                       {"report_id": report_id, "method": result.method, "candidates": added})
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            _log_crash("Saving extraction results", report_id, exc)
            report = session.get(Report, report_id)
            extraction = get_extraction(session, report_id)
            _fail(session, report, extraction, "persistence_failed", {"total_ms": elapsed()}, STAGE_SAVE)
            return
        logger.info("Report extraction ok report=%s method=%s pages=%d candidates=%d ms=%.0f",
                    report_id, result.method, result.page_count, added, timings["total_ms"])


STAGE_LABELS = [
    (STAGE_UPLOAD, "Upload"),
    (STAGE_TEXT, "Extract text"),
    (STAGE_OCR, "OCR fallback"),
    (STAGE_STRUCTURED, "Extract structured data"),
    (STAGE_SAVE, "Save report"),
]


def stages(extraction: Optional[ReportExtraction], candidate_count: int = 0) -> List[dict]:
    """Per-stage state for the UI: pending | active | completed | skipped | failed | not_reached."""
    keys = [k for k, _ in STAGE_LABELS]
    out = [{"key": k, "label": label, "state": "pending", "detail": None} for k, label in STAGE_LABELS]
    by_key = {s["key"]: s for s in out}
    by_key[STAGE_UPLOAD]["state"] = "completed"
    if extraction is None:
        return out
    ocr_used = extraction.method in ("ocr", "pdf_text+ocr")
    current = extraction.stage or STAGE_TEXT
    if extraction.status == "succeeded" or current == STAGE_DONE:
        current_index = len(keys)
    else:
        current_index = keys.index(current) if current in keys else 1
    for i, key in enumerate(keys[1:], start=1):
        row = by_key[key]
        if i < current_index:
            row["state"] = "skipped" if key == STAGE_OCR and not ocr_used else "completed"
        elif i == current_index:
            row["state"] = "failed" if extraction.status == FAILED else "active"
        else:
            row["state"] = "not_reached" if extraction.status == FAILED else "pending"
    if by_key[STAGE_OCR]["state"] == "skipped":
        by_key[STAGE_OCR]["detail"] = "Not required: the PDF has a text layer"
    if extraction.status == "succeeded":
        by_key[STAGE_TEXT]["detail"] = f"{extraction.page_count} page(s)"
        by_key[STAGE_STRUCTURED]["detail"] = (f"{candidate_count} value(s) found" if candidate_count
                                              else "No laboratory values recognised")
    if extraction.status == FAILED:
        failed_key = keys[current_index] if current_index < len(keys) else STAGE_TEXT
        by_key[failed_key]["detail"] = ERROR_MESSAGES.get(extraction.error_code or "",
                                                          ERROR_MESSAGES["internal_error"])
    return out


class ReviewError(ValueError):
    """A review action that is not allowed in the report's current state."""


def date_is_confirmed(report: Report) -> bool:
    if report.date_confirmed is not None:
        return bool(report.date_confirmed)
    # legacy rows (before date confirmation existed): reviewed reports count as confirmed
    return report.status in (CONFIRMED, COMPLETED, LEGACY_READY)


def review_counts(session: Session, report_ids: List[int]) -> dict:
    """{report_id: {detected, confirmed, pending, ignored}} for the given reports."""
    counts = {rid: {"detected": 0, "confirmed": 0, "pending": 0, "ignored": 0} for rid in report_ids}
    if not report_ids:
        return counts
    for cand in session.exec(select(ExtractedMeasurement).where(ExtractedMeasurement.report_id.in_(report_ids))):
        c = counts[cand.report_id]
        if cand.review_status == "rejected":
            c["ignored"] += 1
            continue
        c["detected"] += 1
        if cand.measurement_id is None:
            c["pending"] += 1
    rows =session.exec(select(MedicalMeasurement.report_id).where(MedicalMeasurement.report_id.in_(report_ids))).all()
    for rid in rows:
        counts[rid]["confirmed"] += 1
    return counts


def processing_status(report: Report) -> str:
    if report.status in (UPLOADED, PROCESSING):
        return "processing"
    if report.status == FAILED:
        return "failed"
    return "processed"


def review_status(report: Report, counts: dict) -> Optional[str]:
    """needs_review | partially_confirmed | confirmed (None while processing or after a failure)."""
    if processing_status(report) != "processed":
        return None
    if counts["pending"] == 0 and date_is_confirmed(report):
        return CONFIRMED
    return PARTIALLY_CONFIRMED if counts["confirmed"] else NEEDS_REVIEW


def refresh_status(session: Session, report: Report) -> dict:
    """Recompute the stored lifecycle status from review progress. Returns the counts."""
    session.flush()
    counts = review_counts(session, [report.id])[report.id]
    state = review_status(report, counts)
    if state == NEEDS_REVIEW and counts["detected"] == 0 and counts["ignored"] == 0:
        state = EXTRACTED                     # nothing to review except the report date
    if state:
        report.status = state
        session.add(report)
    return counts


def confirm_date(session: Session, report: Report, report_date: date) -> None:
    """User confirms the report date; records whether it matches a date found in the document."""
    if processing_status(report) == "processing":
        raise ReviewError("This report is still being processed.")
    iso = report_date.isoformat()
    extraction = get_extraction(session, report.id)
    detected = set()
    if extraction:
        for cand in json.loads(extraction.date_candidates or "[]"):
            detected.update([cand.get("value")] + list(cand.get("alternatives") or []))
        report.detected_date = report.detected_date or extraction.document_date
    report.date_source = "extracted" if iso in detected else "user_override"
    report.date_confirmed = True
    report.report_date = iso
    for m in session.exec(select(MedicalMeasurement).where(MedicalMeasurement.report_id == report.id)):
        m.report_date = report_date            # keep the timeline consistent with the confirmed date
        session.add(m)
    session.add(report)


def confirm_candidate(session: Session, report: Report, cand: ExtractedMeasurement) -> MedicalMeasurement:
    if not date_is_confirmed(report):
        raise ReviewError("Confirm the report date first.")
    if cand.measurement_id is not None:
        raise ReviewError("This value is already confirmed.")
    if cand.review_status == "rejected":
        raise ReviewError("This value is ignored. Restore it before confirming.")
    if cand.value is None:
        raise ValueError(f"A value is missing for {cand.test_name}")
    m = MedicalMeasurement(
        test_name=cand.test_name, value=cand.value, unit=cand.unit,
        reference_range=cand.reference_range, flag=cand.flag,
        report_date=date.fromisoformat(report.report_date[:10]),
        hospital=report.hospital, laboratory=report.laboratory, department=report.department,
        comments=("Edited during review" if cand.edited else "Confirmed during review"),
        source_location=f"Page {cand.page}" if cand.page else None,
        report_id=report.id, patient_id=report.patient_id, owner_id=report.owner_id,
    )
    session.add(m)
    session.flush()
    cand.measurement_id = m.id
    cand.review_status = "confirmed"
    session.add(cand)
    return m


def confirm(session: Session, report: Report, report_date: Optional[date],
            candidate_ids: Optional[List[int]] = None) -> int:
    """Confirm the report date (if given) and candidates. Returns the number of measurements created.

    With ``candidate_ids``: confirm exactly those values; other values are left for later review.
    Without (legacy "finish review"): confirm accepted values and ignore the ones still pending.
    """
    if report_date is not None:
        confirm_date(session, report, report_date)
    candidates = session.exec(select(ExtractedMeasurement).where(
        ExtractedMeasurement.report_id == report.id).order_by(ExtractedMeasurement.id)).all()
    created = 0
    if candidate_ids is not None:
        wanted = set(candidate_ids)
        unknown = wanted - {c.id for c in candidates}
        if unknown:
            raise ReviewError("Some values do not belong to this report.")
        for cand in candidates:
            if cand.id in wanted and cand.measurement_id is None and cand.review_status != "rejected":
                confirm_candidate(session, report, cand)
                created += 1
    else:
        if not date_is_confirmed(report):
            raise ReviewError("Confirm the report date first.")
        for cand in candidates:
            if cand.measurement_id is not None:
                continue
            if cand.review_status == "accepted":
                confirm_candidate(session, report, cand)
                created += 1
            elif cand.review_status == "pending":
                cand.review_status = "rejected"
                session.add(cand)
    refresh_status(session, report)
    return created


def add_source_reference(session: Session, report: Report) -> None:
    session.add(SourceReference(owner_id=report.owner_id, report_id=str(report.id), type="document",
                                storage_provider=report.storage_provider,
                                storage_location=f"report:{report.id}"))


def delete_derived(session: Session, report_id: int) -> None:
    session.exec(delete(ExtractedMeasurement).where(ExtractedMeasurement.report_id == report_id))
    session.exec(delete(MedicalMeasurement).where(MedicalMeasurement.report_id == report_id))
    session.exec(delete(ReportExtraction).where(ReportExtraction.report_id == report_id))
    session.exec(delete(ReportSummary).where(ReportSummary.report_id == report_id))
    session.exec(delete(SourceReference).where(SourceReference.report_id == str(report_id)))
