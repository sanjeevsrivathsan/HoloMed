"""Patients and their records.

Every route resolves the patient through `get_path_patient`, which only returns a patient
owned by the signed-in user (404 otherwise), so one patient's data is never reachable
through another patient's id or another user's session.
"""
import io
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import (code_taken, create_patient, get_path_patient, touch, validate_code,
                                    validate_name)
from ..models import AIAnalysis, Instance, MedicalMeasurement, MeasurementRead, Patient, Report, Series, Study, User
from ..services.audit import log_action
from ..services.dicom_service import store_patient_dicom
from ..services.storage import retrieve_file
from ..services.vision import analyses
from ..services.vision.schemas import VisionScreenResponse
from .medical_data import read_dicom_upload, upload_response
from .report import list_report_items
from .vision import attach_analysis, log_screen, run_screen

router = APIRouter(prefix="/api/v1/patients", tags=["Patients"])

Sex = Optional[Literal["female", "male", "other", "unknown"]]
ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


class PatientCreate(BaseModel):
    name: str = Field(..., max_length=200)
    patient_code: Optional[str] = Field(None, max_length=64)
    date_of_birth: Optional[str] = Field(None, pattern=ISO_DATE)
    sex: Sex = None


class PatientUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    patient_code: Optional[str] = Field(None, max_length=64)
    date_of_birth: Optional[str] = Field(None, pattern=ISO_DATE)
    sex: Sex = None


class PatientOut(BaseModel):
    id: str
    patient_code: str
    name: str
    date_of_birth: Optional[str] = None
    sex: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    study_count: int = 0
    report_count: int = 0
    analysis_count: int = 0


class SelectedTarget(BaseModel):
    selected_target: str = Field(..., min_length=1, max_length=64)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() + "Z" if value else None


def _counts(session: Session, model, owner_id: int) -> dict:
    rows = session.exec(select(model.patient_id, func.count()).where(model.owner_id == owner_id)
                        .group_by(model.patient_id)).all()
    return dict(rows)


def _out(patient: Patient, studies: dict, reports: dict, analyses_n: dict) -> PatientOut:
    return PatientOut(id=patient.uid, patient_code=patient.patient_code or "", name=patient.display_name,
                      date_of_birth=patient.date_of_birth, sex=patient.sex,
                      created_at=_iso(patient.created_at), updated_at=_iso(patient.updated_at),
                      study_count=studies.get(patient.id, 0), report_count=reports.get(patient.id, 0),
                      analysis_count=analyses_n.get(patient.id, 0))


def _one(session: Session, patient: Patient) -> PatientOut:
    return _out(patient, _counts(session, Study, patient.owner_id), _counts(session, Report, patient.owner_id),
                _counts(session, AIAnalysis, patient.owner_id))


@router.get("", response_model=List[PatientOut])
def list_patients(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    patients = session.exec(select(Patient).where(Patient.owner_id == user.id).order_by(Patient.id)).all()
    studies, reports, analyses_n = (_counts(session, m, user.id) for m in (Study, Report, AIAnalysis))
    return [_out(p, studies, reports, analyses_n) for p in patients]


@router.post("", response_model=PatientOut, status_code=201)
def create(body: PatientCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    patient = create_patient(session, user, body.name, body.patient_code, body.date_of_birth, body.sex)
    log_action(session, user.id, "patient_created", {"patient_code": patient.patient_code}, patient_id=patient.id)
    session.commit()
    return _one(session, patient)


@router.get("/{patient_uid}", response_model=PatientOut)
def get_patient(patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    return _one(session, patient)


@router.patch("/{patient_uid}", response_model=PatientOut)
def update_patient(body: PatientUpdate, patient: Patient = Depends(get_path_patient),
                   session: Session = Depends(get_session)):
    if body.name is not None:
        patient.display_name = validate_name(body.name)
    if body.patient_code is not None:
        code = validate_code(body.patient_code)
        if code_taken(session, patient.owner_id, code, exclude_id=patient.id):
            raise HTTPException(status_code=409, detail=f"Patient ID {code} already exists.")
        patient.patient_code = code
    if body.date_of_birth is not None:
        patient.date_of_birth = body.date_of_birth
    if body.sex is not None:
        patient.sex = body.sex
    touch(patient)
    session.add(patient)
    log_action(session, patient.owner_id, "patient_updated", {"patient_code": patient.patient_code}, patient_id=patient.id)
    session.commit()
    session.refresh(patient)
    return _one(session, patient)


# ── Imaging ────────────────────────────────────────────────────────────────────

def _header(instance: Instance):
    import pydicom
    data = retrieve_file(instance.storage_key, instance.storage_provider)
    return pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True) if data else None


def _dicom_date(value) -> Optional[str]:
    text = str(value or "")
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) >= 8 and text[:8].isdigit() else None


def imaging_rows(session: Session, patient: Patient) -> list:
    studies = session.exec(select(Study).where(Study.patient_id == patient.id, Study.owner_id == patient.owner_id)
                           .order_by(Study.id)).all()
    latest = {}
    for a in session.exec(select(AIAnalysis).where(AIAnalysis.patient_id == patient.id)
                          .order_by(AIAnalysis.created_at)).all():
        if a.study_id:
            latest[a.study_id] = a
    rows = []
    for study in studies:
        series_rows, header, total = [], None, 0
        for series in session.exec(select(Series).where(Series.study_id == study.id).order_by(Series.id)).all():
            instances = session.exec(select(Instance).where(Instance.series_id == series.id).order_by(Instance.id)).all()
            if not instances:
                continue
            h = _header(instances[0])
            header = header or h
            total += len(instances)
            series_rows.append({
                "series_instance_uid": series.series_instance_uid,
                "modality": series.modality,
                "description": str(getattr(h, "SeriesDescription", "") or "") or None,
                "instance_count": len(instances),
                "first_sop_instance_uid": instances[0].sop_instance_uid,
                "rows": int(h.Rows) if h is not None and getattr(h, "Rows", None) else None,
                "columns": int(h.Columns) if h is not None and getattr(h, "Columns", None) else None,
            })
        analysis = latest.get(study.id)
        rows.append({
            "study_instance_uid": study.study_instance_uid,
            "modality": study.modality,
            "description": study.description or str(getattr(header, "StudyDescription", "") or "") or None,
            "study_date": _dicom_date(getattr(header, "StudyDate", None)),
            "uploaded_at": _iso(study.created_at),
            "series_count": len(series_rows),
            "instance_count": total,
            "series": series_rows,
            "latest_analysis": analyses.summary(session, analysis) if analysis else None,
        })
    return rows


@router.get("/{patient_uid}/imaging")
def list_imaging(patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    return imaging_rows(session, patient)


@router.post("/{patient_uid}/imaging")
async def upload_imaging(file: UploadFile = File(...), user: User = Depends(get_current_user),
                         patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    content = await read_dicom_upload(file)
    return upload_response(store_patient_dicom(session, user, patient, content, file.filename or "upload.dcm"), patient)


@router.post("/{patient_uid}/imaging/{study_uid}/screen", response_model=VisionScreenResponse)
async def screen_study(study_uid: str, target: Optional[str] = None, analysis_id: Optional[str] = None,
                       user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient),
                       session: Session = Depends(get_session)):
    """AI screening of a stored study's first image — no re-upload. A new result is saved to the patient;
    with ``analysis_id`` the run only re-targets that saved analysis (another finding's Grad-CAM)."""
    study = session.exec(select(Study).where(Study.study_instance_uid == study_uid, Study.patient_id == patient.id,
                                             Study.owner_id == user.id)).first()
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    instance = session.exec(select(Instance).join(Series, Series.id == Instance.series_id)
                            .where(Series.study_id == study.id).order_by(Series.id, Instance.id)).first()
    data = retrieve_file(instance.storage_key, instance.storage_provider) if instance else None
    if not data:
        raise HTTPException(status_code=404, detail="Study has no stored image")
    if analysis_id:
        analysis = _owned_analysis(session, patient, analysis_id)
        if analysis.study_id != study.id:
            raise HTTPException(status_code=404, detail="Analysis not found")
    result, provider_name = await run_screen(data, target, user)
    if analysis_id:
        analysis.selected_target = result.explanation.target_pathology
        session.add(analysis)
        session.commit()
    else:
        analysis = analyses.record(session, user, patient, result, data, provider_name, study, instance)
    attach_analysis(result, analysis, patient, session)
    log_screen(session, user, result, patient)
    return result


# ── Reports, clinical values, analyses, timeline ───────────────────────────────

@router.get("/{patient_uid}/reports")
def list_reports(user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient),
                 session: Session = Depends(get_session)):
    return list_report_items(session, user, patient.id)


def _measurements(session: Session, patient: Patient) -> list:
    return session.exec(select(MedicalMeasurement).where(MedicalMeasurement.patient_id == patient.id,
                                                         MedicalMeasurement.owner_id == patient.owner_id)
                        .order_by(MedicalMeasurement.report_date.desc())).all()


@router.get("/{patient_uid}/clinical")
def clinical(patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    return {"patient_id": patient.uid,
            "measurements": [MeasurementRead.model_validate(m) for m in _measurements(session, patient)]}


def _owned_analysis(session: Session, patient: Patient, analysis_uid: str) -> AIAnalysis:
    analysis = session.exec(select(AIAnalysis).where(AIAnalysis.uid == analysis_uid, AIAnalysis.patient_id == patient.id,
                                                     AIAnalysis.owner_id == patient.owner_id)).first()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@router.get("/{patient_uid}/analyses")
def list_analyses(patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    rows = session.exec(select(AIAnalysis).where(AIAnalysis.patient_id == patient.id,
                                                 AIAnalysis.owner_id == patient.owner_id)
                        .order_by(AIAnalysis.created_at.desc())).all()
    return [analyses.summary(session, a) for a in rows]


@router.get("/{patient_uid}/analyses/{analysis_uid}")
def get_analysis(analysis_uid: str, patient: Patient = Depends(get_path_patient), session: Session = Depends(get_session)):
    return analyses.reopen(session, _owned_analysis(session, patient, analysis_uid))


@router.patch("/{patient_uid}/analyses/{analysis_uid}")
def update_analysis(analysis_uid: str, body: SelectedTarget, patient: Patient = Depends(get_path_patient),
                    session: Session = Depends(get_session)):
    analysis = _owned_analysis(session, patient, analysis_uid)
    analysis.selected_target = body.selected_target
    session.add(analysis)
    session.commit()
    return analyses.summary(session, analysis)


@router.get("/{patient_uid}/timeline")
def timeline(user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient),
             session: Session = Depends(get_session)):
    """Chronological events of one patient: imaging uploads, AI screenings, reports and confirmed values."""
    events = []
    for study in imaging_rows(session, patient):
        events.append({"type": "imaging", "date": study["study_date"] or study["uploaded_at"][:10],
                       "at": study["uploaded_at"], "title": f"{study['modality'] or 'Imaging'} study uploaded",
                       "ref": study["study_instance_uid"]})
    for a in session.exec(select(AIAnalysis).where(AIAnalysis.patient_id == patient.id,
                                                   AIAnalysis.owner_id == user.id)).all():
        events.append({"type": "ai_screening", "date": a.created_at.date().isoformat(), "at": _iso(a.created_at),
                       "title": f"AI screening — model output {a.primary_pathology} ({a.primary_score:.4f})",
                       "ref": a.uid})
    for r in list_report_items(session, user, patient.id):
        events.append({"type": "report", "date": str(r["report_date"])[:10], "at": _iso(r["uploaded_at"]),
                       "title": r["title"], "ref": str(r["id"])})
    for m in _measurements(session, patient):
        events.append({"type": "measurement", "date": m.report_date.isoformat(), "at": None,
                       "title": f"{m.test_name}: {m.value:g} {m.unit}", "ref": str(m.id)})
    events.sort(key=lambda e: (e["date"] or "", e["at"] or ""), reverse=True)
    return {"patient_id": patient.uid, "events": events}
