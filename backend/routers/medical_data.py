import io
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import create_patient as create_patient_record
from ..dependencies.patient import get_active_patient
from ..models import Instance, Patient, User
from ..services.audit import log_action  # noqa: F401  (re-exported: other routers import it from here)
from ..services.dicom_service import MAX_UPLOAD_SIZE, StoredDicom, store_patient_dicom

router = APIRouter(prefix="/api/v1/medical-data", tags=["Medical Data"])


class PatientCreate(BaseModel):
    display_name: str
    external_id: Optional[str] = None


class PatientRead(BaseModel):
    id: int
    uid: Optional[str] = None
    owner_id: int
    patient_code: Optional[str] = None
    external_id: Optional[str] = None
    display_name: str


@router.post("/patients", response_model=PatientRead)
def create_patient(patient_in: PatientCreate, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    patient = create_patient_record(session, user, patient_in.display_name)
    if patient_in.external_id:
        patient.external_id = patient_in.external_id
        session.add(patient)
    log_action(session, user.id, "patient_created", {"patient_id": patient.id}, patient_id=patient.id)
    session.commit()
    session.refresh(patient)
    return patient


@router.get("/patients", response_model=list[PatientRead])
def list_patients(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return session.exec(select(Patient).where(Patient.owner_id == user.id).order_by(Patient.id)).all()


def upload_response(stored: StoredDicom, patient: Patient) -> dict:
    return {
        "instance_id": stored.instance.id,
        "patient_id": patient.uid,
        "study_instance_uid": stored.study.study_instance_uid,
        "series_instance_uid": stored.series.series_instance_uid,
        "sop_instance_uid": stored.instance.sop_instance_uid,
        "modality": stored.study.modality,
        "created": stored.created,
    }


async def read_dicom_upload(file: UploadFile) -> bytes:
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large: uploaded file exceeds 50 MiB limit")
    return content


@router.post("/dicom/upload")
async def upload_dicom(file: UploadFile = File(...), user: User = Depends(get_current_user),
                       patient: Patient = Depends(get_active_patient), session: Session = Depends(get_session)):
    content = await read_dicom_upload(file)
    stored = store_patient_dicom(session, user, patient, content, file.filename or "upload.dcm")
    return upload_response(stored, patient)


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
