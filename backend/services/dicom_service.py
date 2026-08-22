import io
from typing import Dict
import pydicom
from fastapi import HTTPException
from .storage import store_file

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MiB

def validate_and_extract(file_bytes: bytes) -> Dict[str, str]:
    if len(file_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MiB)")
    try:
        ds = pydicom.dcmread(io.BytesIO(file_bytes), stop_before_pixels=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid DICOM file")

    metadata = {
        "StudyInstanceUID": str(ds.get("StudyInstanceUID", "")),
        "SeriesInstanceUID": str(ds.get("SeriesInstanceUID", "")),
        "SOPInstanceUID": str(ds.get("SOPInstanceUID", "")),
        "Modality": str(ds.get("Modality", "")),
    }
    return metadata

def store_dicom(file_bytes: bytes, filename: str) -> str:
    return store_file(file_bytes, filename)
