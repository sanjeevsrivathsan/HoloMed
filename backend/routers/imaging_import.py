"""Bulk DICOM import into a patient (Imaging → Import: DICOM files, a folder, or one ZIP archive).

  POST   /api/v1/patients/{patient_uid}/imaging/imports                  {"source": "files"|"folder"|"zip"}
  POST   /api/v1/patients/{patient_uid}/imaging/imports/{job_id}/files   multipart `files` (a batch)
  PUT    /api/v1/patients/{patient_uid}/imaging/imports/{job_id}/archive raw application/zip body
  POST   /api/v1/patients/{patient_uid}/imaging/imports/{job_id}/start
  GET    /api/v1/patients/{patient_uid}/imaging/imports/{job_id}         progress and summary
  DELETE /api/v1/patients/{patient_uid}/imaging/imports/{job_id}         cancel

Every route resolves the patient through get_path_patient (owned by the signed-in user, else 404) and
a job is only visible to the user and patient it was created for. Nothing sent by the client (form
fields, file names, DICOM headers) selects the patient.
"""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import get_path_patient
from ..models import Patient, User
from ..services import dicom_import
from ..services.dicom_import import clean_label

router = APIRouter(prefix="/api/v1/patients/{patient_uid}/imaging/imports", tags=["Imaging import"])


class ImportCreate(BaseModel):
    source: Literal["files", "folder", "zip"]


@router.post("", status_code=201)
def create_import(body: ImportCreate, user: User = Depends(get_current_user),
                  patient: Patient = Depends(get_path_patient)):
    return dicom_import.create_job(user, patient, body.source).view()


@router.get("/{job_id}")
def get_import(job_id: str, user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient)):
    return dicom_import.get_job(job_id, user, patient).view()


@router.post("/{job_id}/files")
def add_files(job_id: str, files: List[UploadFile] = File(...), user: User = Depends(get_current_user),
              patient: Patient = Depends(get_path_patient)):
    """A batch of files. The file name may carry the folder-relative path (diagnostics only)."""
    job = dicom_import.get_job(job_id, user, patient)
    dicom_import.add_files(job, [(clean_label(f.filename), f.file) for f in files])
    return job.view()


@router.put("/{job_id}/archive")
async def add_archive(job_id: str, request: Request, filename: Optional[str] = None,
                      user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient)):
    """The ZIP archive as the raw request body, streamed to disk under the size limit."""
    job = dicom_import.get_job(job_id, user, patient)
    length = request.headers.get("content-length")
    await dicom_import.add_archive(job, filename or "archive.zip", request.stream(),
                                   int(length) if length and length.isdigit() else None)
    return job.view()


@router.post("/{job_id}/start", status_code=202)
def start_import(job_id: str, user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient),
                 session: Session = Depends(get_session)):
    job = dicom_import.get_job(job_id, user, patient)
    dicom_import.start_job(job, session.get_bind(), user, patient)
    return job.view()


@router.delete("/{job_id}")
def cancel_import(job_id: str, user: User = Depends(get_current_user), patient: Patient = Depends(get_path_patient)):
    job = dicom_import.get_job(job_id, user, patient)
    dicom_import.cancel_job(job)
    return job.view()
