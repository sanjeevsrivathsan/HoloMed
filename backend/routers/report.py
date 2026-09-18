import io
import json
import logging
import os
from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import get_active_patient, get_optional_patient
from ..models import (ExtractedMeasurement, ExtractedMeasurementRead, MedicalMeasurement, Patient, Report,
                      ReportExtractionRead, ReportRead, ReportSummary, ReportSummaryRead, User)
from ..routers.medical_data import log_action
from ..services import document_extraction, report_pipeline as pipeline
from ..services.explanation import report_summary
from ..services.storage import retrieve_file, store_file

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

MAX_REPORT_BYTES = 50 * 1024 * 1024
FORMATS = {
    "pdf": {"extension": ".pdf", "mime_type": "application/pdf", "label": "PDF"},
    "png": {"extension": ".png", "mime_type": "image/png", "label": "PNG image"},
    "jpeg": {"extension": ".jpg", "mime_type": "image/jpeg", "label": "JPEG image"},
}


def supported_formats() -> List[str]:
    return ["pdf", "png", "jpeg"] if document_extraction.ocr_available() else ["pdf"]


class ReportOut(ReportRead):
    """Report metadata plus separate processing and review state."""
    processing_status: str = "processed"          # processing | processed | failed
    review_status: Optional[str] = None           # needs_review | partially_confirmed | confirmed
    date_confirmed: bool = False
    detected_count: int = 0                       # extracted values not ignored (incl. confirmed)
    confirmed_count: int = 0                      # canonical measurements from this report
    pending_count: int = 0                        # extracted values still awaiting a decision
    ignored_count: int = 0


class ReportListItem(ReportOut):
    extraction_status: Optional[str] = None
    candidate_count: int = 0                      # kept for compatibility (= detected_count)
    measurement_count: int = 0                    # kept for compatibility (= confirmed_count)
    summary: Optional[ReportSummaryRead] = None


class ReportSummaryOut(ReportSummaryRead):
    safety_message: str = report_summary.SAFETY_MESSAGE
    text_model: Optional[str] = None
    generator: Optional[str] = None


class CandidateUpdate(BaseModel):
    test_name: Optional[str] = Field(None, min_length=1, max_length=120)
    value: Optional[float] = None
    unit: Optional[str] = Field(None, max_length=40)
    reference_range: Optional[str] = Field(None, max_length=pipeline.lab_parser.MAX_RANGE_CHARS)
    flag: Optional[Literal["normal", "high", "low", "abnormal", "unknown"]] = None
    review_status: Optional[Literal["pending", "accepted", "rejected"]] = None


class DateConfirm(BaseModel):
    report_date: date


class ReviewConfirm(BaseModel):
    report_date: Optional[date] = None
    candidate_ids: Optional[List[int]] = None


class ReviewConfirmResult(BaseModel):
    report_id: int
    status: str
    review_status: Optional[str] = None
    measurements_created: int


def _owned_report(session: Session, report_id: int, user: User) -> Report:
    report = session.get(Report, report_id)
    if not report or report.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


def _read(report: Report, counts: Optional[dict] = None, **extra) -> dict:
    counts = counts or {"detected": 0, "confirmed": 0, "pending": 0, "ignored": 0}
    data = ReportRead.model_validate(report).model_dump()
    data.update(
        status=pipeline.public_status(report.status),
        processing_status=pipeline.processing_status(report),
        review_status=pipeline.review_status(report, counts),
        date_confirmed=pipeline.date_is_confirmed(report),
        detected_count=counts["detected"], confirmed_count=counts["confirmed"],
        pending_count=counts["pending"], ignored_count=counts["ignored"],
    )
    data.update(extra)
    return data


def _read_one(session: Session, report: Report) -> dict:
    return _read(report, pipeline.review_counts(session, [report.id])[report.id])


def _summary_read(summary: Optional[ReportSummary]) -> Optional[ReportSummaryRead]:
    return ReportSummaryRead.model_validate(summary) if summary else None


@router.get("/capabilities")
def get_capabilities(user: User = Depends(get_current_user)):
    fmts = supported_formats()
    return {
        "formats": [FORMATS[f] for f in fmts],
        "max_bytes": MAX_REPORT_BYTES,
        "ocr_available": document_extraction.ocr_available(),
        "document_types": [{"value": v, "label": label} for v, label in pipeline.DOCUMENT_TYPES],
    }


@router.post("", response_model=ReportOut)
async def upload_report(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    type: str = Form("Other"),
    hospital: Optional[str] = Form(None),
    laboratory: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    doctor: Optional[str] = Form(None),
    report_date: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    patient: Patient = Depends(get_active_patient),
    session: Session = Depends(get_session)
):
    content = await file.read(MAX_REPORT_BYTES + 1)
    if len(content) > MAX_REPORT_BYTES:
        raise HTTPException(status_code=413, detail="File too large. The maximum size is 50 MB.")
    if not content:
        raise HTTPException(status_code=400, detail="The file is empty.")
    fmt = document_extraction.detect_format(content)
    if fmt not in supported_formats():
        allowed = ", ".join(FORMATS[f]["label"] for f in supported_formats())
        raise HTTPException(status_code=415, detail=f"Unsupported file type. Supported formats: {allowed}.")
    if type not in pipeline.ALLOWED_TYPES:
        raise HTTPException(status_code=422, detail="Unknown document type.")
    filename = os.path.basename(file.filename or "") or f"report{FORMATS[fmt]['extension']}"
    title = (title or "").strip() or os.path.splitext(filename)[0][:120] or "Untitled Report"
    if len(title) > 200:
        raise HTTPException(status_code=422, detail="Title is too long.")

    storage_key = store_file(content, filename)
    report = Report(
        owner_id=user.id,
        patient_id=patient.id,
        title=title,
        type=type,
        hospital=hospital,
        laboratory=laboratory,
        department=department,
        doctor=doctor,
        report_date=report_date or datetime.utcnow().isoformat(),
        date_source="user_entered" if report_date else "upload_default",
        date_confirmed=bool(report_date),
        status=pipeline.UPLOADED,
        original_filename=filename,
        mime_type=FORMATS[fmt]["mime_type"],
        file_size=len(content),
        storage_key=storage_key,
    )
    session.add(report)
    session.commit()
    session.refresh(report)
    pipeline.add_source_reference(session, report)
    log_action(session, user.id, "report_uploaded", {"report_id": report.id, "format": fmt}, patient_id=patient.id)
    session.commit()

    pipeline.start(session, report)
    background.add_task(pipeline.process, session.get_bind(), report.id)
    session.refresh(report)
    return _read_one(session, report)


@router.get("", response_model=List[ReportListItem])
def list_reports(
    patient_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    active: Optional[Patient] = Depends(get_optional_patient),
    session: Session = Depends(get_session)
):
    return list_report_items(session, user, active.id if active else patient_id)


def list_report_items(session: Session, user: User, patient_id: Optional[int]) -> list:
    stmt = select(Report).where(Report.owner_id == user.id)
    if patient_id:
        stmt = stmt.where(Report.patient_id == patient_id)
    reports = session.exec(stmt.order_by(Report.uploaded_at.desc())).all()
    ids = [r.id for r in reports]
    if not ids:
        return []
    extraction_status = {e.report_id: e.status for e in session.exec(
        select(pipeline.ReportExtraction).where(pipeline.ReportExtraction.report_id.in_(ids)))}
    counts = pipeline.review_counts(session, ids)
    summaries = {s.report_id: s for s in session.exec(
        select(ReportSummary).where(ReportSummary.report_id.in_(ids), ReportSummary.owner_id == user.id))}
    return [_read(r, counts[r.id], extraction_status=extraction_status.get(r.id),
                  candidate_count=counts[r.id]["detected"], measurement_count=counts[r.id]["confirmed"],
                  summary=_summary_read(summaries.get(r.id)))
            for r in reports]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    return _read_one(session, _owned_report(session, report_id, user))


@router.get("/{report_id}/download")
def download_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    file_bytes = retrieve_file(report.storage_key, report.storage_provider)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File content not found in storage")

    log_action(session, user.id, "report_downloaded", {"report_id": report.id})
    session.commit()
    return StreamingResponse(io.BytesIO(file_bytes), media_type=report.mime_type,
                             headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    pipeline.delete_derived(session, report_id)
    session.delete(report)
    log_action(session, user.id, "report_deleted", {"report_id": report_id})
    session.commit()
    return {"status": "deleted"}


def _extraction_read(session: Session, report_id: int) -> ReportExtractionRead:
    extraction = pipeline.get_extraction(session, report_id)
    if extraction is None:
        raise HTTPException(status_code=404, detail="This report has not been processed.")
    candidates = session.exec(select(ExtractedMeasurement).where(
        ExtractedMeasurement.report_id == report_id).order_by(ExtractedMeasurement.id)).all()
    warnings = json.loads(extraction.warnings or "[]")
    if extraction.error_code:
        warnings = [pipeline.ERROR_MESSAGES.get(extraction.error_code, pipeline.ERROR_MESSAGES["internal_error"])] \
            + warnings
    open_candidates = sum(1 for c in candidates if c.review_status != "rejected")
    return ReportExtractionRead(
        report_id=report_id, status=extraction.status, stage=extraction.stage,
        stages=pipeline.stages(extraction, open_candidates),
        method=extraction.method, quality=extraction.quality,
        page_count=extraction.page_count, char_count=extraction.char_count, text=extraction.text,
        document_date=extraction.document_date,
        date_candidates=json.loads(extraction.date_candidates or "[]"),
        error_code=extraction.error_code, warnings=warnings,
        timings=json.loads(extraction.timings or "{}"),
        candidates=[ExtractedMeasurementRead.model_validate(c) for c in candidates],
    )


@router.get("/{report_id}/extraction", response_model=ReportExtractionRead)
def get_extraction(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    _owned_report(session, report_id, user)
    return _extraction_read(session, report_id)


@router.post("/{report_id}/extraction/retry", response_model=ReportOut)
def retry_extraction(
    report_id: int,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    extraction = pipeline.get_extraction(session, report_id)
    if report.status == pipeline.PROCESSING and not pipeline.is_stale(extraction):
        raise HTTPException(status_code=409, detail="This report is still being processed.")
    counts = pipeline.review_counts(session, [report_id])[report_id]
    if counts["confirmed"]:
        raise HTTPException(status_code=409, detail="Values for this report are already confirmed.")
    pipeline.start(session, report)
    log_action(session, user.id, "report_extraction_retried", {"report_id": report_id})
    session.commit()
    background.add_task(pipeline.process, session.get_bind(), report_id)
    session.refresh(report)
    return _read_one(session, report)


@router.patch("/{report_id}/candidates/{candidate_id}", response_model=ExtractedMeasurementRead)
def update_candidate(
    report_id: int,
    candidate_id: int,
    body: CandidateUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    cand = _owned_candidate(session, report_id, candidate_id, user)
    if cand.measurement_id is not None:
        raise HTTPException(status_code=409, detail="This value is already confirmed.")
    changes = body.model_dump(exclude_unset=True)
    edited_fields = {"test_name", "value", "unit", "reference_range", "flag"}
    for key, value in changes.items():
        if key in {"test_name", "unit", "reference_range"} and isinstance(value, str):
            value = value.strip()
        if key == "reference_range" and not value:
            value = None
        if key in edited_fields and value != getattr(cand, key):
            cand.edited = True
            if key == "value":
                cand.value_text = "" if value is None else f"{value:g}"
        setattr(cand, key, value)
    session.add(cand)
    pipeline.refresh_status(session, report)
    session.commit()
    session.refresh(cand)
    return cand


def _owned_candidate(session: Session, report_id: int, candidate_id: int, user: User) -> ExtractedMeasurement:
    cand = session.get(ExtractedMeasurement, candidate_id)
    if not cand or cand.report_id != report_id or cand.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Value not found")
    return cand


def _require_processed(report: Report) -> None:
    if pipeline.processing_status(report) != "processed":
        raise HTTPException(status_code=409, detail="This report is not ready for review.")


@router.post("/{report_id}/date/confirm", response_model=ReportOut)
def confirm_report_date(
    report_id: int,
    body: DateConfirm,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    _require_processed(report)
    pipeline.confirm_date(session, report, body.report_date)
    pipeline.refresh_status(session, report)
    log_action(session, user.id, "report_date_confirmed", {"report_id": report_id, "source": report.date_source})
    session.commit()
    session.refresh(report)
    return _read_one(session, report)


@router.post("/{report_id}/candidates/{candidate_id}/confirm", response_model=ExtractedMeasurementRead)
def confirm_candidate(
    report_id: int,
    candidate_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    _require_processed(report)
    cand = _owned_candidate(session, report_id, candidate_id, user)
    try:
        pipeline.confirm_candidate(session, report, cand)
    except pipeline.ReviewError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    pipeline.refresh_status(session, report)
    log_action(session, user.id, "report_value_confirmed", {"report_id": report_id, "candidate_id": candidate_id})
    session.commit()
    session.refresh(cand)
    return cand


@router.post("/{report_id}/review/confirm", response_model=ReviewConfirmResult)
def confirm_review(
    report_id: int,
    body: ReviewConfirm,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    _require_processed(report)
    try:
        created = pipeline.confirm(session, report, body.report_date, body.candidate_ids)
    except pipeline.ReviewError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    log_action(session, user.id, "report_review_confirmed",
               {"report_id": report_id, "measurements_created": created})
    session.commit()
    counts = pipeline.review_counts(session, [report.id])[report.id]
    return ReviewConfirmResult(report_id=report_id, status=pipeline.public_status(report.status),
                               review_status=pipeline.review_status(report, counts),
                               measurements_created=created)


@router.get("/{report_id}/summary", response_model=Optional[ReportSummaryOut])
def get_report_summary(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    _owned_report(session, report_id, user)
    summary = session.exec(select(ReportSummary).where(ReportSummary.report_id == report_id)).first()
    return ReportSummaryOut.model_validate(summary) if summary else None


def _summary_input(session: Session, report: Report, user: User) -> report_summary.SummaryInput:
    extraction = pipeline.get_extraction(session, report.id)
    measurements = session.exec(select(MedicalMeasurement).where(
        MedicalMeasurement.report_id == report.id, MedicalMeasurement.owner_id == user.id)
        .order_by(MedicalMeasurement.id)).all()
    candidates = {c.measurement_id: c for c in session.exec(select(ExtractedMeasurement).where(
        ExtractedMeasurement.report_id == report.id, ExtractedMeasurement.measurement_id.is_not(None)))}
    counts = pipeline.review_counts(session, [report.id])[report.id]
    this_date = measurements[0].report_date if measurements else None
    history = {}
    names = {m.test_name for m in measurements}
    if names and this_date:
        earlier = session.exec(select(MedicalMeasurement, Report).join(
            Report, Report.id == MedicalMeasurement.report_id).where(
            MedicalMeasurement.owner_id == user.id, MedicalMeasurement.test_name.in_(names),
            MedicalMeasurement.report_id != report.id, MedicalMeasurement.report_date < this_date)
            .order_by(MedicalMeasurement.report_date)).all()
        for m, r in earlier:
            history.setdefault(m.test_name, []).append(report_summary.HistoryPoint(
                value=m.value, value_text=f"{m.value:g}", unit=m.unit, report_date=m.report_date.isoformat(),
                report_title=r.title))
    items = []
    for m in measurements:
        cand = candidates.get(m.id)
        items.append(report_summary.SummaryMeasurement(
            test_name=m.test_name, value_text=(cand.value_text if cand and cand.value_text else f"{m.value:g}"),
            unit=m.unit, reference_range=m.reference_range, flag=m.flag, page=cand.page if cand else None))
    return report_summary.SummaryInput(
        title=report.title, report_type=report.type, report_date=report.report_date,
        date_confirmed=pipeline.date_is_confirmed(report), laboratory=report.laboratory or report.hospital,
        source_filename=report.original_filename, measurements=items,
        values={m.test_name: m.value for m in measurements}, history=history,
        pending_count=counts["pending"], ignored_count=counts["ignored"],
        extraction_method=extraction.method if extraction else None,
        extraction_quality=extraction.quality if extraction else None,
        text=(extraction.text if extraction and extraction.status == "succeeded" and not counts["detected"]
              else None),
    )


@router.post("/{report_id}/summary", response_model=ReportSummaryOut)
def create_report_summary(
    report_id: int,
    mode: str = Form("standard"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = _owned_report(session, report_id, user)
    if mode not in report_summary.MODES:
        raise HTTPException(status_code=422, detail="Unknown summary mode.")
    if pipeline.processing_status(report) != "processed":
        raise HTTPException(status_code=409, detail="This report has not been processed.")
    inp = _summary_input(session, report, user)
    counts = pipeline.review_counts(session, [report.id])[report.id]
    if counts["detected"] and not inp.measurements:
        raise HTTPException(status_code=409,
                            detail="Confirm at least one extracted value before generating a summary.")
    if not inp.measurements and not inp.text:
        raise HTTPException(status_code=409, detail="There is no confirmed or extracted content to summarise yet.")
    try:
        result = report_summary.generate(inp, mode)
    except report_summary.SummaryUnavailable:
        raise HTTPException(status_code=503,
                            detail="The text AI service is not available. Start it and try again.")
    except ValueError:
        raise HTTPException(status_code=502,
                            detail="The AI summary did not pass the safety checks. Please try again.")

    existing = session.exec(select(ReportSummary).where(ReportSummary.report_id == report_id)).first()
    if existing:
        session.delete(existing)
    summary = ReportSummary(report_id=report_id, owner_id=user.id, mode=mode,
                            sections=json.dumps(result.sections))
    session.add(summary)
    log_action(session, user.id, "report_summary_generated",
               {"report_id": report_id, "mode": mode, "ms": result.elapsed_ms})
    session.commit()
    session.refresh(summary)
    return ReportSummaryOut(**ReportSummaryRead.model_validate(summary).model_dump(),
                            text_model=result.text_model, generator=result.generator)
