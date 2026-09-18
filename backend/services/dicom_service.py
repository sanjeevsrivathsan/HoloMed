import io
from dataclasses import dataclass
from typing import Dict

import pydicom
from fastapi import HTTPException
from sqlmodel import Session, select

from ..models import Instance, Patient, Series, Study, User
from .audit import log_action
from .storage import store_file

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MiB
_UID_KEYS = ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")


def validate_and_extract(file_bytes: bytes) -> Dict[str, str]:
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MiB)")
    try:
        ds = pydicom.dcmread(io.BytesIO(file_bytes), stop_before_pixels=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid DICOM file")

    metadata = {key: str(ds.get(key, "") or "") for key in _UID_KEYS}
    missing = [key for key in _UID_KEYS if not metadata[key]]
    if missing:
        raise HTTPException(status_code=400, detail=f"Invalid DICOM file: missing {', '.join(missing)}")
    metadata["Modality"] = str(ds.get("Modality", "") or "")
    metadata["StudyDescription"] = str(ds.get("StudyDescription", "") or "")
    metadata["SeriesDescription"] = str(ds.get("SeriesDescription", "") or "")
    return metadata


def store_dicom(file_bytes: bytes, filename: str) -> str:
    return store_file(file_bytes, filename)


@dataclass
class StoredDicom:
    study: Study
    series: Series
    instance: Instance
    meta: Dict[str, str]
    created: bool


def store_patient_dicom(session: Session, user: User, patient: Patient, content: bytes, filename: str) -> StoredDicom:
    """Store an unchanged DICOM file under `patient` and index it as study → series → instance.

    Re-uploading an instance the patient already has reuses the stored copy.
    """
    meta = validate_and_extract(content)
    study = session.exec(select(Study).where(Study.study_instance_uid == meta["StudyInstanceUID"],
                                             Study.patient_id == patient.id,
                                             Study.owner_id == user.id)).first()
    if study is None:
        study = Study(owner_id=user.id, patient_id=patient.id, study_instance_uid=meta["StudyInstanceUID"],
                      modality=meta["Modality"] or None,
                      description=meta["StudyDescription"] or meta["SeriesDescription"] or None)
        session.add(study)
        session.flush()
        log_action(session, user.id, "study_created", {"study_id": study.id, "study_uid": study.study_instance_uid},
                   patient_id=patient.id)

    series = session.exec(select(Series).where(Series.series_instance_uid == meta["SeriesInstanceUID"],
                                               Series.study_id == study.id)).first()
    if series is None:
        series = Series(owner_id=user.id, study_id=study.id, series_instance_uid=meta["SeriesInstanceUID"],
                        modality=meta["Modality"] or None)
        session.add(series)
        session.flush()
        log_action(session, user.id, "series_created", {"series_id": series.id, "series_uid": series.series_instance_uid},
                   patient_id=patient.id)

    instance = session.exec(select(Instance).where(Instance.sop_instance_uid == meta["SOPInstanceUID"],
                                                   Instance.series_id == series.id)).first()
    created = instance is None
    if created:
        instance = Instance(owner_id=user.id, series_id=series.id, sop_instance_uid=meta["SOPInstanceUID"],
                            storage_key=store_dicom(content, filename))
        session.add(instance)
        session.flush()
        log_action(session, user.id, "dicom_uploaded", {"instance_id": instance.id, "sop_uid": instance.sop_instance_uid},
                   patient_id=patient.id)
    session.commit()
    for row in (study, series, instance):
        session.refresh(row)
    return StoredDicom(study=study, series=series, instance=instance, meta=meta, created=created)
