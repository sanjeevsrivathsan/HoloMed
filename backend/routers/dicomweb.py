from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
from typing import List, Optional

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
def qido_studies(request: Request, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = select(Study).where(Study.owner_id == user.id)
    studies = session.exec(stmt).all()
    log_action(session, user.id, "dicomweb_qido_studies")
    if wants_dicom_json(request):
        wanted = _uid_filter(request, "StudyInstanceUID")
        return JSONResponse([study_dicom_json(session, user, s) for s in studies
                             if wanted is None or s.study_instance_uid in wanted], media_type=DICOM_JSON)
    return [StudyMeta(
        StudyInstanceUID=s.study_instance_uid,
        Modality=s.modality,
        CreatedDate=s.created_at.isoformat(),
        Description=s.description,
    ) for s in studies]


@router.get("/studies/{study_uid}", response_model=StudyMeta)
def qido_study(study_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
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
def qido_series(study_uid: str, request: Request, user: User = Depends(get_current_user),
                session: Session = Depends(get_session)):
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
    if wants_dicom_json(request):
        study = _owned_study(session, user, study_uid)
        wanted = _uid_filter(request, "SeriesInstanceUID")
        return JSONResponse([series_dicom_json(session, user, study, s) for s in series_list
                             if wanted is None or s.series_instance_uid in wanted], media_type=DICOM_JSON)
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
def qido_instances(study_uid: str, series_uid: str, request: Request, user: User = Depends(get_current_user),
                   session: Session = Depends(get_session)):
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
    if wants_dicom_json(request):
        study = _owned_study(session, user, study_uid)
        series = session.exec(select(Series).where(Series.series_instance_uid == series_uid,
                                                   Series.study_id == study.id)).first()
        return JSONResponse([instance_dicom_json(study, series, i) for i in instances], media_type=DICOM_JSON)
    return [InstanceMeta(SOPInstanceUID=i.sop_instance_uid) for i in instances]


@router.get("/studies/{study_uid}/metadata")
def wado_study_metadata(study_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = (
        select(Instance)
        .join(Series)
        .join(Study)
        .where(Study.study_instance_uid == study_uid, Study.owner_id == user.id)
    )
    instances = session.exec(stmt).all()
    if not instances:
        raise HTTPException(status_code=404, detail="Study/instances not found")
        
    metadata_list = []
    import io
    import pydicom
    for instance in instances:
        file_bytes = retrieve_file(instance.storage_key, instance.storage_provider)
        if file_bytes:
            ds = pydicom.dcmread(io.BytesIO(file_bytes), stop_before_pixels=True)
            # Suppress specific VRs that cause issues or are too large
            metadata_list.append(ds.to_json_dict(suppress_invalid_tags=True))
            
    log_action(session, user.id, "dicomweb_wado_study_metadata", {"study_uid": study_uid})
    from fastapi.responses import JSONResponse
    return JSONResponse(content=metadata_list, media_type="application/dicom+json")


@router.get("/studies/{study_uid}/series/{series_uid}/metadata")
def wado_series_metadata(study_uid: str, series_uid: str, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    stmt = (
        select(Instance)
        .join(Series)
        .join(Study)
        .where(
            Series.series_instance_uid == series_uid,
            Study.study_instance_uid == study_uid,
            Study.owner_id == user.id
        )
    )
    instances = session.exec(stmt).all()
    if not instances:
        raise HTTPException(status_code=404, detail="Series/instances not found")
        
    metadata_list = []
    import io
    import pydicom
    for instance in instances:
        file_bytes = retrieve_file(instance.storage_key, instance.storage_provider)
        if file_bytes:
            ds = pydicom.dcmread(io.BytesIO(file_bytes), stop_before_pixels=True)
            metadata_list.append(ds.to_json_dict(suppress_invalid_tags=True))
            
    log_action(session, user.id, "dicomweb_wado_series_metadata", {"study_uid": study_uid, "series_uid": series_uid})
    from fastapi.responses import JSONResponse
    return JSONResponse(content=metadata_list, media_type="application/dicom+json")


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
    import uuid
    boundary = uuid.uuid4().hex
    # Construct multipart body as bytes to avoid encoding issues
    multipart_body = (
        f"--{boundary}\r\n".encode("utf-8")
        + b"Content-Type: application/dicom\r\n\r\n"
        + file_bytes
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    log_action(session, user.id, "dicomweb_wado_instance", {"study_uid": study_uid, "series_uid": series_uid, "sop_uid": sop_uid})
    return Response(content=multipart_body, media_type=f"multipart/related; type=application/dicom; boundary={boundary}")


# ── Standard DICOMweb representations (used by the OHIF viewer) ─────────────────
# QIDO-RS responses above keep HoloMed's compact JSON for the HoloMed UI. Clients that ask for
# application/dicom+json (OHIF) receive standard DICOM JSON instead, and pixel data is served by
# the WADO-RS frames endpoint below. Every query stays scoped to the signed-in owner.

DICOM_JSON = "application/dicom+json"

_FRAME_CONTENT_TYPES = {
    "1.2.840.10008.1.2.4.50": "image/jpeg", "1.2.840.10008.1.2.4.51": "image/jpeg",
    "1.2.840.10008.1.2.4.57": "image/jpeg", "1.2.840.10008.1.2.4.70": "image/jpeg",
    "1.2.840.10008.1.2.4.80": "image/jls", "1.2.840.10008.1.2.4.81": "image/jls",
    "1.2.840.10008.1.2.4.90": "image/jp2", "1.2.840.10008.1.2.4.91": "image/jp2",
    "1.2.840.10008.1.2.5": "image/dicom-rle",
}


def wants_dicom_json(request: Request) -> bool:
    return DICOM_JSON in request.headers.get("accept", "").lower()


def _read_header(instance: Instance):
    import io
    import pydicom
    data = retrieve_file(instance.storage_key, instance.storage_provider)
    if not data:
        return None
    return pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)


def _dicom_json(values: dict) -> dict:
    """Build a DICOM JSON object from {keyword: value}; empty values are omitted."""
    from pydicom import Dataset
    ds = Dataset()
    for keyword, value in values.items():
        if value not in (None, "", []):
            setattr(ds, keyword, value)
    return ds.to_json_dict()


def _uid_filter(request: Request, name: str) -> Optional[set]:
    raw = request.query_params.get(name)
    if not raw:
        return None
    return {u for u in raw.replace("\\", ",").split(",") if u}


def _instances_for(session: Session, user: User, study_id: int, series_id: Optional[int] = None) -> List[Instance]:
    stmt = select(Instance).join(Series, Series.id == Instance.series_id).where(
        Series.study_id == study_id, Instance.owner_id == user.id)
    if series_id is not None:
        stmt = stmt.where(Series.id == series_id)
    return session.exec(stmt).all()


def study_dicom_json(session: Session, user: User, study: Study) -> dict:
    series = session.exec(select(Series).where(Series.study_id == study.id)).all()
    instances = _instances_for(session, user, study.id)
    header = _read_header(instances[0]) if instances else None
    get = (lambda k: getattr(header, k, None)) if header is not None else (lambda k: None)
    modalities = sorted({s.modality for s in series if s.modality})
    return _dicom_json({
        "StudyInstanceUID": study.study_instance_uid,
        "StudyDate": get("StudyDate"),
        "StudyTime": get("StudyTime"),
        "AccessionNumber": get("AccessionNumber"),
        "PatientName": get("PatientName"),
        "PatientID": get("PatientID"),
        "PatientBirthDate": get("PatientBirthDate"),
        "PatientSex": get("PatientSex"),
        "StudyDescription": get("StudyDescription") or study.description,
        "StudyID": get("StudyID"),
        "ModalitiesInStudy": modalities,
        "NumberOfStudyRelatedSeries": len(series),
        "NumberOfStudyRelatedInstances": len(instances),
    })


def series_dicom_json(session: Session, user: User, study: Study, series: Series) -> dict:
    instances = _instances_for(session, user, study.id, series.id)
    header = _read_header(instances[0]) if instances else None
    get = (lambda k: getattr(header, k, None)) if header is not None else (lambda k: None)
    return _dicom_json({
        "StudyInstanceUID": study.study_instance_uid,
        "SeriesInstanceUID": series.series_instance_uid,
        "Modality": series.modality or get("Modality"),
        "SeriesDescription": get("SeriesDescription"),
        "SeriesNumber": get("SeriesNumber"),
        "SeriesDate": get("SeriesDate"),
        "SeriesTime": get("SeriesTime"),
        "NumberOfSeriesRelatedInstances": len(instances),
    })


def instance_dicom_json(study: Study, series: Series, instance: Instance) -> dict:
    header = _read_header(instance)
    get = (lambda k: getattr(header, k, None)) if header is not None else (lambda k: None)
    return _dicom_json({
        "StudyInstanceUID": study.study_instance_uid,
        "SeriesInstanceUID": series.series_instance_uid,
        "SOPInstanceUID": instance.sop_instance_uid,
        "SOPClassUID": get("SOPClassUID"),
        "InstanceNumber": get("InstanceNumber"),
        "Rows": get("Rows"),
        "Columns": get("Columns"),
        "NumberOfFrames": get("NumberOfFrames"),
    })


def _owned_study(session: Session, user: User, study_uid: str) -> Study:
    study = session.exec(select(Study).where(Study.study_instance_uid == study_uid,
                                             Study.owner_id == user.id)).first()
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return study


def _frame_parts(data: bytes, frame_numbers: List[int]) -> List[tuple]:
    """[(content_type, bytes)] for the requested 1-based frame numbers."""
    import io
    import pydicom
    from pydicom.encaps import generate_frames

    ds = pydicom.dcmread(io.BytesIO(data))
    ts = str(ds.file_meta.TransferSyntaxUID)
    n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
    if any(n < 1 or n > n_frames for n in frame_numbers):
        raise HTTPException(status_code=404, detail="Frame not found")
    if ds.file_meta.TransferSyntaxUID.is_compressed:
        frames = list(generate_frames(ds.PixelData, number_of_frames=n_frames))
        content_type = f"{_FRAME_CONTENT_TYPES.get(ts, 'application/octet-stream')}; transfer-syntax={ts}"
        return [(content_type, frames[n - 1]) for n in frame_numbers]
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    bits = int(ds.BitsAllocated)
    if bits == 1:
        frame_size = (ds.Rows * ds.Columns * samples + 7) // 8
    else:
        frame_size = ds.Rows * ds.Columns * samples * ((bits + 7) // 8)
    pixels = ds.PixelData
    content_type = f"application/octet-stream; transfer-syntax={ts}"
    return [(content_type, pixels[(n - 1) * frame_size: n * frame_size]) for n in frame_numbers]


@router.get("/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/frames/{frame_list}")
def wado_frames(study_uid: str, series_uid: str, sop_uid: str, frame_list: str,
                user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    """WADO-RS RetrieveFrames: pixel data of the requested frames as multipart/related."""
    try:
        frame_numbers = [int(f) for f in frame_list.split(",") if f.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid frame list")
    if not frame_numbers:
        raise HTTPException(status_code=400, detail="Invalid frame list")
    study = _owned_study(session, user, study_uid)
    instance = session.exec(select(Instance).join(Series, Series.id == Instance.series_id).where(
        Instance.sop_instance_uid == sop_uid, Series.series_instance_uid == series_uid,
        Series.study_id == study.id, Instance.owner_id == user.id)).first()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    data = retrieve_file(instance.storage_key, instance.storage_provider)
    if not data:
        raise HTTPException(status_code=404, detail="File not found in storage")
    parts = _frame_parts(data, frame_numbers)
    log_action(session, user.id, "dicomweb_wado_frames", {"study_uid": study_uid, "series_uid": series_uid,
                                                          "sop_uid": sop_uid, "frames": len(frame_numbers)})
    import uuid
    boundary = uuid.uuid4().hex
    body = b""
    for content_type, payload in parts:
        body += f"--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode() + bytes(payload) + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    part_type = parts[0][0].split(";")[0]
    return Response(content=body, media_type=f'multipart/related; type="{part_type}"; boundary={boundary}')
