"""Report ingestion lifecycle.

    uploaded → processing → extracted | needs_review → confirmed → completed
                         ↘ failed (retry allowed)

The original upload is stored once and never changed. Extraction output
(text, measurement candidates) lives in derived tables; canonical
MedicalMeasurement rows are only created when the user confirms values.
Legacy reports with status "ready" (created before this pipeline) are shown
as completed.
"""
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.engine import Engine
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
CONFIRMED = "confirmed"
COMPLETED = "completed"
FAILED = "failed"
LEGACY_READY = "ready"

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
    "internal_error": "The document could not be processed.",
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


def _fail(session: Session, report: Report, extraction: ReportExtraction, code: str, timings: dict):
    extraction.status = FAILED
    extraction.error_code = code
    extraction.timings = json.dumps(timings)
    extraction.updated_at = _now()
    report.status = FAILED
    session.add(extraction)
    session.add(report)
    log_action(session, report.owner_id, "report_extraction_failed", {"report_id": report.id, "error": code})
    session.commit()
    logger.info("Report extraction failed report=%s code=%s", report.id, code)


def process(engine: Engine, report_id: int) -> None:
    """Run extraction + parsing for one report (called as a background task)."""
    started = time.perf_counter()
    with Session(engine) as session:
        report = session.get(Report, report_id)
        extraction = get_extraction(session, report_id)
        if report is None or extraction is None:
            return
        data = retrieve_file(report.storage_key, report.storage_provider)
        if not data:
            _fail(session, report, extraction, "file_missing", {})
            return
        try:
            result = document_extraction.extract_text(data)
        except document_extraction.ExtractionError as exc:
            _fail(session, report, extraction, exc.code,
                  {"total_ms": round((time.perf_counter() - started) * 1000, 1)})
            return
        except Exception:  # never leave a report stuck in "processing"
            logger.exception("Report extraction crashed report=%s", report_id)
            _fail(session, report, extraction, "internal_error", {})
            return

        t_parse = time.perf_counter()
        parsed = lab_parser.parse_report_text(result.text, ocr=result.method != "pdf_text")
        timings = dict(result.timings)
        timings["parse_ms"] = round((time.perf_counter() - t_parse) * 1000, 1)

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
        extraction.method = result.method
        extraction.quality = result.quality
        extraction.page_count = result.page_count
        extraction.char_count = len(result.text)
        extraction.text = result.text
        extraction.document_date = parsed.document_date
        extraction.warnings = json.dumps(warnings)
        timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        extraction.timings = json.dumps(timings)
        extraction.updated_at = _now()
        if parsed.document_date and "T" in (report.report_date or ""):
            # The upload time was only a placeholder; show the date printed in the document
            # (the user still confirms or corrects it during review).
            report.report_date = parsed.document_date
        report.status = NEEDS_REVIEW if added else EXTRACTED
        session.add(extraction)
        session.add(report)
        log_action(session, report.owner_id, "report_extraction_completed",
                   {"report_id": report_id, "method": result.method, "candidates": added})
        session.commit()
        logger.info("Report extraction ok report=%s method=%s pages=%d candidates=%d ms=%.0f",
                    report_id, result.method, result.page_count, added, timings["total_ms"])


def confirm(session: Session, report: Report, report_date: date) -> int:
    """Turn accepted candidates into canonical measurements. Returns the number created."""
    candidates = session.exec(select(ExtractedMeasurement).where(
        ExtractedMeasurement.report_id == report.id)).all()
    created = 0
    for cand in candidates:
        if cand.measurement_id is not None:
            continue
        if cand.review_status == "accepted":
            if cand.value is None:
                raise ValueError(f"A value is missing for {cand.test_name}")
            m = MedicalMeasurement(
                test_name=cand.test_name, value=cand.value, unit=cand.unit,
                reference_range=cand.reference_range, flag=cand.flag, report_date=report_date,
                hospital=report.hospital, laboratory=report.laboratory, department=report.department,
                comments=("Edited during review" if cand.edited else "Confirmed during review"),
                source_location=f"Page {cand.page}" if cand.page else None,
                report_id=report.id, patient_id=report.patient_id, owner_id=report.owner_id,
            )
            session.add(m)
            session.flush()
            cand.measurement_id = m.id
            cand.review_status = "confirmed"
            created += 1
        elif cand.review_status == "pending":
            cand.review_status = "rejected"
        session.add(cand)
    report.report_date = report_date.isoformat()
    if report.status != COMPLETED:
        report.status = CONFIRMED
    session.add(report)
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
