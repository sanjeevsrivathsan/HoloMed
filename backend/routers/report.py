import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime
import json

from ..database import get_session
from ..models import Report, User, Patient
from ..dependencies.auth import get_current_user
from ..services.storage import store_file, retrieve_file
from ..routers.medical_data import log_action

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])

@router.post("")
async def upload_report(
    file: UploadFile = File(...),
    title: str = Form("Untitled Report"),
    type: str = Form("Other"),
    hospital: Optional[str] = Form(None),
    laboratory: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    doctor: Optional[str] = Form(None),
    report_date: Optional[str] = Form(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
        
    # Get or create patient (just like DICOM upload)
    patient = session.exec(select(Patient).where(Patient.owner_id == user.id)).first()
    if not patient:
        patient = Patient(owner_id=user.id, display_name="Demo Patient")
        session.add(patient)
        session.commit()
        session.refresh(patient)
        
    storage_key = store_file(content, file.filename)
    
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
        status="ready",  # No processing pipeline yet
        original_filename=file.filename,
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(content),
        storage_key=storage_key
    )
    
    session.add(report)
    session.commit()
    session.refresh(report)
    
    log_action(session, user.id, "report_uploaded", {"report_id": report.id, "title": report.title})
    
    return report

@router.get("")
def list_reports(
    patient_id: Optional[int] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    stmt = select(Report).where(Report.owner_id == user.id)
    if patient_id:
        stmt = stmt.where(Report.patient_id == patient_id)
    reports = session.exec(stmt).all()
    return reports

@router.get("/{report_id}")
def get_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = session.get(Report, report_id)
    if not report or report.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report

@router.get("/{report_id}/download")
def download_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = session.get(Report, report_id)
    if not report or report.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
        
    file_bytes = retrieve_file(report.storage_key, report.storage_provider)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File content not found in storage")
        
    log_action(session, user.id, "report_downloaded", {"report_id": report.id})
    return StreamingResponse(io.BytesIO(file_bytes), media_type=report.mime_type)

@router.delete("/{report_id}")
def delete_report(
    report_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    report = session.get(Report, report_id)
    if not report or report.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
        
    session.delete(report)
    session.commit()
    log_action(session, user.id, "report_deleted", {"report_id": report_id})
    return {"status": "deleted"}
