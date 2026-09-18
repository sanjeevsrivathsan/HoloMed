import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select
from pydantic import BaseModel
from typing import List, Optional
from ..database import get_session
from ..models import (
    Patient,
    Study,
    Series,
    Instance,
    User,
    AuditLog
)
from ..services.dicom_service import validate_and_extract, store_dicom
from ..dependencies.auth import get_current_user

router = APIRouter(prefix="/api/v1/medical-data", tags=["Medical Data"])

def log_action(session: Session, user_id: int, action: str, details: dict = None):
    # Strip PHI just in case
    safe_details = {k: v for k, v in (details or {}).items() if "name" not in k.lower() and "dob" not in k.lower()}
    import json
    log_entry = AuditLog(user_id=user_id, action=action, details=json.dumps(safe_details) if safe_details else None)
    session.add(log_entry)

class PatientCreate(BaseModel):
    display_name: str
    external_id: Optional[str] = None

class PatientRead(BaseModel):
    id: int
    owner_id: int
    external_id: Optional[str] = None
    display_name: str

@router.post("/patients", response_model=PatientRead)
def create_patient(patient_in: PatientCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    patient = Patient(owner_id=user.id, display_name=patient_in.display_name, external_id=patient_in.external_id)
    session.add(patient)
    session.commit()
    session.refresh(patient)
    log_action(session, user.id, "patient_created", {"patient_id": patient.id})
    session.commit()
    return patient

@router.get("/patients", response_model=list[PatientRead])
def list_patients(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = select(Patient).where(Patient.owner_id == user.id)
    return session.exec(stmt).all()

@router.post("/dicom/upload")
async def upload_dicom(file: UploadFile = File(...), user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    content = await file.read()
    # Enforce 50 MiB upload limit
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large: uploaded file exceeds 50 MiB limit")
    meta = validate_and_extract(content)
    storage_key = store_dicom(content, file.filename)

    # 1. Patient
    patient = session.exec(select(Patient).where(Patient.owner_id == user.id)).first()
    if not patient:
        patient = Patient(owner_id=user.id, display_name="Demo Patient")
        session.add(patient)
        session.commit()
        session.refresh(patient)
        log_action(session, user.id, "patient_created", {"patient_id": patient.id})

    # 2. Study
    study = session.exec(select(Study).where(Study.study_instance_uid == meta["StudyInstanceUID"]).where(Study.owner_id == user.id)).first()
    if not study:
        study = Study(
            owner_id=user.id,
            patient_id=patient.id,
            study_instance_uid=meta["StudyInstanceUID"],
            modality=meta["Modality"],
        )
        session.add(study)
        session.commit()
        session.refresh(study)
        log_action(session, user.id, "study_created", {"study_id": study.id, "study_uid": meta["StudyInstanceUID"]})

    # 3. Series
    series = session.exec(select(Series).where(Series.series_instance_uid == meta["SeriesInstanceUID"]).where(Series.owner_id == user.id)).first()
    if not series:
        series = Series(
            owner_id=user.id,
            study_id=study.id,
            series_instance_uid=meta["SeriesInstanceUID"],
            modality=meta["Modality"],
        )
        session.add(series)
        session.commit()
        session.refresh(series)
        log_action(session, user.id, "series_created", {"series_id": series.id, "series_uid": meta["SeriesInstanceUID"]})

    # 4. Instance
    instance = Instance(
        owner_id=user.id,
        series_id=series.id,
        sop_instance_uid=meta["SOPInstanceUID"],
        storage_key=storage_key,
    )
    session.add(instance)
    log_action(session, user.id, "dicom_uploaded", {"instance_id": instance.id, "sop_uid": meta["SOPInstanceUID"]})
    session.commit()
    session.refresh(instance)
    return {"instance_id": instance.id, "study_instance_uid": meta["StudyInstanceUID"]}

@router.get("/instances/{instance_id}/download")
def download_instance(instance_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    instance = session.get(Instance, instance_id)
    if not instance or instance.owner_id != user.id:
        raise HTTPException(status_code=404, detail="Instance not found")

    from ..services.storage import retrieve_file
    file_bytes = retrieve_file(instance.storage_key, instance.storage_provider)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File content not found in storage")

    log_action(session, user.id, "dicom_downloaded", {"instance_id": instance.id})
    session.commit()

    return StreamingResponse(io.BytesIO(file_bytes), media_type="application/dicom")
