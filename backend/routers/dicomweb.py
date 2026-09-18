"""DICOMweb (QIDO-RS / WADO-RS) over the caller's stored DICOM.

Two roots expose the same handlers:
  /api/v1/dicomweb                          — every study the signed-in user owns
  /api/v1/patients/{patient_uid}/dicomweb   — one owned patient's studies (used by OHIF)
The patient root is what HoloMed launches OHIF with, so OHIF can only ever list and load
the selected patient's studies.
"""
import fnmatch
import io
import json
import uuid
from dataclasses import dataclass
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..dependencies.patient import owned_patient
from ..models import AuditLog, Instance, Patient, Series, Study, User
from ..models.dicomweb_schemas import InstanceMeta, SeriesMeta, StudyMeta
from ..services.storage import retrieve_file

router = APIRouter(prefix="/api/v1/dicomweb", tags=["DICOMweb"])
patient_router = APIRouter(prefix="/api/v1/patients/{patient_uid}/dicomweb", tags=["DICOMweb"])

DICOM_JSON = "application/dicom+json"

_FRAME_CONTENT_TYPES = {
    "1.2.840.10008.1.2.4.50": "image/jpeg", "1.2.840.10008.1.2.4.51": "image/jpeg",
    "1.2.840.10008.1.2.4.57": "image/jpeg", "1.2.840.10008.1.2.4.70": "image/jpeg",
    "1.2.840.10008.1.2.4.80": "image/jls", "1.2.840.10008.1.2.4.81": "image/jls",
    "1.2.840.10008.1.2.4.90": "image/jp2", "1.2.840.10008.1.2.4.91": "image/jp2",
    "1.2.840.10008.1.2.5": "image/dicom-rle",
}

# Mirrors the "dicomweb" data source in frontend/ohif/app-config.js.
OHIF_SOURCE_OPTIONS = {
    "qidoSupportsIncludeField": False, "imageRendering": "wadors", "thumbnailRendering": "wadors",
    "enableStudyLazyLoad": True, "supportsFuzzyMatching": False, "supportsWildcard": True,
    "staticWado": False, "omitQuotationForMultipartRequest": True,
}


@dataclass
class DicomScope:
    user: User
    patient: Optional[Patient]

    @property
    def patient_id(self) -> Optional[int]:
        return self.patient.id if self.patient else None


def get_scope(request: Request, user: User = Depends(get_current_user),
              session: Session = Depends(get_session)) -> DicomScope:
    patient_uid = request.path_params.get("patient_uid")
    return DicomScope(user=user, patient=owned_patient(session, user, patient_uid) if patient_uid else None)


def log_action(session: Session, scope: DicomScope, action: str, details: dict | None = None):
    safe_details = {k: v for k, v in (details or {}).items() if "name" not in k.lower() and "dob" not in k.lower()}
    session.add(AuditLog(user_id=scope.user.id, patient_id=scope.patient_id, action=action,
                         details=json.dumps(safe_details) if safe_details else None))
    session.commit()


# ── Scoped queries ──────────────────────────────────────────────────────────────

def _studies(session: Session, scope: DicomScope, study_uid: Optional[str] = None) -> List[Study]:
    stmt = select(Study).where(Study.owner_id == scope.user.id)
    if scope.patient is not None:
        stmt = stmt.where(Study.patient_id == scope.patient.id)
    if study_uid is not None:
        stmt = stmt.where(Study.study_instance_uid == study_uid)
    return session.exec(stmt.order_by(Study.id)).all()


def _owned_study(session: Session, scope: DicomScope, study_uid: str) -> Study:
    studies = _studies(session, scope, study_uid)
    if not studies:
        raise HTTPException(status_code=404, detail="Study not found")
    return studies[0]


def _series_of(session: Session, study: Study, series_uid: Optional[str] = None) -> List[Series]:
    stmt = select(Series).where(Series.study_id == study.id)
    if series_uid is not None:
        stmt = stmt.where(Series.series_instance_uid == series_uid)
    return session.exec(stmt.order_by(Series.id)).all()


def _owned_series(session: Session, scope: DicomScope, study_uid: str, series_uid: str) -> tuple:
    study = _owned_study(session, scope, study_uid)
    series = _series_of(session, study, series_uid)
    if not series:
        raise HTTPException(status_code=404, detail="Series not found")
    return study, series[0]


def _instances_for(session: Session, scope: DicomScope, study: Study, series: Optional[Series] = None) -> List[Instance]:
    stmt = select(Instance).join(Series, Series.id == Instance.series_id).where(
        Series.study_id == study.id, Instance.owner_id == scope.user.id)
    if series is not None:
        stmt = stmt.where(Series.id == series.id)
    return session.exec(stmt.order_by(Instance.id)).all()


# ── Representations ────────────────────────────────────────────────────────────

def wants_dicom_json(request: Request) -> bool:
    return DICOM_JSON in request.headers.get("accept", "").lower()


def _read_header(instance: Instance):
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


def _patient_id_filter(request: Request) -> Optional[str]:
    """QIDO PatientID match key (OHIF sends it as 00100020 to find a patient's other studies)."""
    return request.query_params.get("PatientID") or request.query_params.get("00100020") or None


def _matches(value: Optional[str], pattern: str) -> bool:
    value = value or ""
    return fnmatch.fnmatchcase(value, pattern) if any(c in pattern for c in "*?") else value == pattern


def study_dicom_json(session: Session, scope: DicomScope, study: Study) -> dict:
    series = _series_of(session, study)
    instances = _instances_for(session, scope, study)
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


def series_dicom_json(session: Session, scope: DicomScope, study: Study, series: Series) -> dict:
    instances = _instances_for(session, scope, study, series)
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


def _full_metadata(instances: List[Instance]) -> list:
    import pydicom
    out = []
    for instance in instances:
        data = retrieve_file(instance.storage_key, instance.storage_provider)
        if data:
            ds = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)
            out.append(ds.to_json_dict(suppress_invalid_tags=True))
    return out


def _frame_parts(data: bytes, frame_numbers: List[int]) -> List[tuple]:
    """[(content_type, bytes)] for the requested 1-based frame numbers."""
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


# ── QIDO-RS ────────────────────────────────────────────────────────────────────
# HoloMed's own UI gets compact JSON; clients asking for application/dicom+json (OHIF) get
# standard DICOM JSON.

def qido_studies(request: Request, scope: DicomScope = Depends(get_scope), session: Session = Depends(get_session)):
    studies = _studies(session, scope)
    log_action(session, scope, "dicomweb_qido_studies")
    wanted = _uid_filter(request, "StudyInstanceUID")
    if wanted is not None:
        studies = [s for s in studies if s.study_instance_uid in wanted]
    patient_key = _patient_id_filter(request)
    if wants_dicom_json(request):
        rows = [study_dicom_json(session, scope, s) for s in studies]
        if patient_key:
            rows = [r for r in rows if _matches((r.get("00100020", {}).get("Value") or [None])[0], patient_key)]
        return JSONResponse(rows, media_type=DICOM_JSON)
    return [StudyMeta(StudyInstanceUID=s.study_instance_uid, Modality=s.modality,
                      CreatedDate=s.created_at.isoformat(), Description=s.description) for s in studies]


def qido_study(study_uid: str, scope: DicomScope = Depends(get_scope), session: Session = Depends(get_session)):
    study = _owned_study(session, scope, study_uid)
    log_action(session, scope, "dicomweb_qido_study", {"uid": study_uid})
    return StudyMeta(StudyInstanceUID=study.study_instance_uid, Modality=study.modality,
                     CreatedDate=study.created_at.isoformat(), Description=study.description)


def qido_series(study_uid: str, request: Request, scope: DicomScope = Depends(get_scope),
                session: Session = Depends(get_session)):
    study = _owned_study(session, scope, study_uid)
    series_list = _series_of(session, study)
    if not series_list:
        raise HTTPException(status_code=404, detail="Series not found")
    log_action(session, scope, "dicomweb_qido_series", {"study_uid": study_uid})
    if wants_dicom_json(request):
        wanted = _uid_filter(request, "SeriesInstanceUID")
        return JSONResponse([series_dicom_json(session, scope, study, s) for s in series_list
                             if wanted is None or s.series_instance_uid in wanted], media_type=DICOM_JSON)
    return [SeriesMeta(SeriesInstanceUID=s.series_instance_uid, Modality=s.modality) for s in series_list]


def qido_series_detail(study_uid: str, series_uid: str, scope: DicomScope = Depends(get_scope),
                       session: Session = Depends(get_session)):
    _, series = _owned_series(session, scope, study_uid, series_uid)
    log_action(session, scope, "dicomweb_qido_series_detail", {"study_uid": study_uid, "series_uid": series_uid})
    return SeriesMeta(SeriesInstanceUID=series.series_instance_uid, Modality=series.modality)


def qido_instances(study_uid: str, series_uid: str, request: Request, scope: DicomScope = Depends(get_scope),
                   session: Session = Depends(get_session)):
    study, series = _owned_series(session, scope, study_uid, series_uid)
    instances = _instances_for(session, scope, study, series)
    if not instances:
        raise HTTPException(status_code=404, detail="Instances not found")
    log_action(session, scope, "dicomweb_qido_instances", {"study_uid": study_uid, "series_uid": series_uid})
    if wants_dicom_json(request):
        return JSONResponse([instance_dicom_json(study, series, i) for i in instances], media_type=DICOM_JSON)
    return [InstanceMeta(SOPInstanceUID=i.sop_instance_uid) for i in instances]


# ── WADO-RS ────────────────────────────────────────────────────────────────────

def wado_study_metadata(study_uid: str, scope: DicomScope = Depends(get_scope), session: Session = Depends(get_session)):
    study = _owned_study(session, scope, study_uid)
    instances = _instances_for(session, scope, study)
    if not instances:
        raise HTTPException(status_code=404, detail="Study/instances not found")
    log_action(session, scope, "dicomweb_wado_study_metadata", {"study_uid": study_uid})
    return JSONResponse(content=_full_metadata(instances), media_type=DICOM_JSON)


def wado_series_metadata(study_uid: str, series_uid: str, scope: DicomScope = Depends(get_scope),
                         session: Session = Depends(get_session)):
    study, series = _owned_series(session, scope, study_uid, series_uid)
    instances = _instances_for(session, scope, study, series)
    if not instances:
        raise HTTPException(status_code=404, detail="Series/instances not found")
    log_action(session, scope, "dicomweb_wado_series_metadata", {"study_uid": study_uid, "series_uid": series_uid})
    return JSONResponse(content=_full_metadata(instances), media_type=DICOM_JSON)


def _owned_instance(session: Session, scope: DicomScope, study_uid: str, series_uid: str, sop_uid: str) -> Instance:
    study, series = _owned_series(session, scope, study_uid, series_uid)
    instance = next((i for i in _instances_for(session, scope, study, series) if i.sop_instance_uid == sop_uid), None)
    if instance is None:
        raise HTTPException(status_code=404, detail="Instance not found")
    return instance


def wado_instance(study_uid: str, series_uid: str, sop_uid: str, scope: DicomScope = Depends(get_scope),
                  session: Session = Depends(get_session)):
    instance = _owned_instance(session, scope, study_uid, series_uid, sop_uid)
    file_bytes = retrieve_file(instance.storage_key, instance.storage_provider)
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not found in storage")
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\n".encode() + b"Content-Type: application/dicom\r\n\r\n"
            + file_bytes + f"\r\n--{boundary}--\r\n".encode())
    log_action(session, scope, "dicomweb_wado_instance", {"study_uid": study_uid, "series_uid": series_uid, "sop_uid": sop_uid})
    return Response(content=body, media_type=f"multipart/related; type=application/dicom; boundary={boundary}")


def wado_frames(study_uid: str, series_uid: str, sop_uid: str, frame_list: str,
                scope: DicomScope = Depends(get_scope), session: Session = Depends(get_session)):
    """WADO-RS RetrieveFrames: pixel data of the requested frames as multipart/related."""
    try:
        frame_numbers = [int(f) for f in frame_list.split(",") if f.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid frame list")
    if not frame_numbers:
        raise HTTPException(status_code=400, detail="Invalid frame list")
    instance = _owned_instance(session, scope, study_uid, series_uid, sop_uid)
    data = retrieve_file(instance.storage_key, instance.storage_provider)
    if not data:
        raise HTTPException(status_code=404, detail="File not found in storage")
    parts = _frame_parts(data, frame_numbers)
    log_action(session, scope, "dicomweb_wado_frames", {"study_uid": study_uid, "series_uid": series_uid,
                                                        "sop_uid": sop_uid, "frames": len(frame_numbers)})
    boundary = uuid.uuid4().hex
    body = b""
    for content_type, payload in parts:
        body += f"--{boundary}\r\nContent-Type: {content_type}\r\n\r\n".encode() + bytes(payload) + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    part_type = parts[0][0].split(";")[0]
    return Response(content=body, media_type=f'multipart/related; type="{part_type}"; boundary={boundary}')


_ROUTES = [
    ("/studies", qido_studies, None),
    ("/studies/{study_uid}", qido_study, StudyMeta),
    ("/studies/{study_uid}/series", qido_series, None),
    ("/studies/{study_uid}/series/{series_uid}", qido_series_detail, SeriesMeta),
    ("/studies/{study_uid}/series/{series_uid}/instances", qido_instances, None),
    ("/studies/{study_uid}/metadata", wado_study_metadata, None),
    ("/studies/{study_uid}/series/{series_uid}/metadata", wado_series_metadata, None),
    ("/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}", wado_instance, None),
    ("/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/frames/{frame_list}", wado_frames, None),
]
for _path, _endpoint, _model in _ROUTES:
    for _router in (router, patient_router):
        _router.add_api_route(_path, _endpoint, methods=["GET"], response_model=_model)


@patient_router.get("/ohif-config")
def ohif_config(scope: DicomScope = Depends(get_scope)):
    """Data source definition for OHIF's `dicomwebproxy` source: this patient's DICOMweb roots."""
    root = f"/api/v1/patients/{scope.patient.uid}/dicomweb"
    return {"servers": {"dicomWeb": [{
        "name": "holomed", "friendlyName": "HoloMed patient DICOMweb",
        "qidoRoot": root, "wadoRoot": root, "wadoUriRoot": root, **OHIF_SOURCE_OPTIONS,
    }]}}
