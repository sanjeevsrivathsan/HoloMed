from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select
from typing import List

from ..dependencies.auth import get_current_user
from ..models import Study, Series, Instance, AuditLog, User
from ..database import get_session
from ..services.storage import retrieve_file
from ..models.dicomweb_schemas import StudyMeta, SeriesMeta, InstanceMeta

router = APIRouter(prefix="/api/v1/dicomweb", tags=["DICOMweb"])


def log_action(session: Session, user_id: int, action: str, details: dict | None = None):
    # Simple audit logging (mirroring existing medical_data router behavior)
    safe_details = {k: v for k, v in (details or {}).items() if "name" not in k.lower() and "dob" not in k.lower()}
    import json
    entry = AuditLog(user_id=user_id, action=action, details=json.dumps(safe_details) if safe_details else None)
    session.add(entry)
    session.commit()


@router.get("/studies", response_model=List[StudyMeta])
def qido_studies(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = select(Study).where(Study.owner_id == user.id)
    studies = session.exec(stmt).all()
    log_action(session, user.id, "dicomweb_qido_studies")
    return [StudyMeta(
        StudyInstanceUID=s.study_instance_uid,
        Modality=s.modality,
        CreatedDate=s.created_at.isoformat(),
        Description=s.description,
    ) for s in studies]


@router.get("/studies/{study_uid}", response_model=StudyMeta)
def qido_study(study_uid: str, user: User = Depends(get_current_user), session: Session = Depends(lambda: Session())):
    stmt = select(Study).where(Study.study_instance_uid == study_uid, Study.owner_id == user.id)
    study = session.exec(stmt).first()
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    log_action(session, user.id, "dicomweb_qido_study", {"uid": study_uid})
    return StudyMeta(
        StudyInstanceUID=study.study_instance_uid,
        Modality=study.modality,
        CreatedDate=study.created_at.isoformat(),
        Description=study.description,
    )


@router.get("/studies/{study_uid}/series", response_model=List[SeriesMeta])
def qido_series(study_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = (
        select(Series)
        .where(
            Series.study_id == select(Study.id).where(Study.study_instance_uid == study_uid, Study.owner_id == user.id).scalar_subquery()
        )
    )
    series_list = session.exec(stmt).all()
    if not series_list:
        raise HTTPException(status_code=404, detail="Series not found")
    log_action(session, user.id, "dicomweb_qido_series", {"study_uid": study_uid})
    return [SeriesMeta(SeriesInstanceUID=s.series_instance_uid, Modality=s.modality) for s in series_list]


@router.get("/studies/{study_uid}/series/{series_uid}", response_model=SeriesMeta)
def qido_series_detail(study_uid: str, series_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = (
        select(Series)
        .where(
            Series.series_instance_uid == series_uid,
            Series.study_id == select(Study.id).where(Study.study_instance_uid == study_uid, Study.owner_id == user.id).scalar_subquery(),
        )
    )
    series = session.exec(stmt).first()
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    log_action(session, user.id, "dicomweb_qido_series_detail", {"study_uid": study_uid, "series_uid": series_uid})
    return SeriesMeta(SeriesInstanceUID=series.series_instance_uid, Modality=series.modality)


@router.get("/studies/{study_uid}/series/{series_uid}/instances", response_model=List[InstanceMeta])
def qido_instances(study_uid: str, series_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = (
        select(Instance)
        .where(
            Instance.series_id == select(Series.id).where(
                Series.series_instance_uid == series_uid,
                Series.study_id == select(Study.id).where(Study.study_instance_uid == study_uid, Study.owner_id == user.id).scalar_subquery(),
            ).scalar_subquery()
        )
    )
    instances = session.exec(stmt).all()
    if not instances:
        raise HTTPException(status_code=404, detail="Instances not found")
    log_action(session, user.id, "dicomweb_qido_instances", {"study_uid": study_uid, "series_uid": series_uid})
    return [InstanceMeta(SOPInstanceUID=i.sop_instance_uid) for i in instances]


@router.get("/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}")
def wado_instance(study_uid: str, series_uid: str, sop_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    # Verify ownership chain
    stmt = (
        select(Instance)
        .where(
            Instance.sop_instance_uid == sop_uid,
            Instance.series_id == select(Series.id).where(
                Series.series_instance_uid == series_uid,
                Series.study_id == select(Study.id).where(Study.study_instance_uid == study_uid, Study.owner_id == user.id).scalar_subquery(),
            ).scalar_subquery(),
        )
    )
    instance = session.exec(stmt).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    # Retrieve raw DICOM file from storage abstraction
    file_bytes = retrieve_file(instance.storage_key, instance.storage_provider)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not found in storage")
    # Build multipart/related response expected by OHIF (boundary must be unique per response)
    boundary = "OHIFBoundary"
    multipart_body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/dicom\r\n\r\n"
        f"{file_bytes.decode('latin1')}\r\n"
        f"--{boundary}--\r\n"
    )
    log_action(session, user.id, "dicomweb_wado_instance", {"study_uid": study_uid, "series_uid": series_uid, "sop_uid": sop_uid})
    return Response(content=multipart_body, media_type=f"multipart/related; type=application/dicom; boundary={boundary}")
