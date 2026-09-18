"""DICOMweb for OHIF: DICOM JSON on request (content negotiation), WADO-RS frames, ownership.
Synthetic DICOM, plus the de-identified SIIM chest X-ray when it is present locally."""
import io
import os
from pathlib import Path

import numpy as np
import pydicom
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.encaps import encapsulate
from pydicom.uid import ExplicitVRLittleEndian, JPEGBaseline8Bit, generate_uid
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend.database import get_session
from backend.main import app
from backend.services import storage

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
DICOM_JSON = {"Accept": "application/dicom+json"}
STUDY_UID, SERIES_UID = generate_uid(), generate_uid()


def get_session_override():
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))
    SQLModel.metadata.create_all(engine)
    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def make_dicom(sop_uid: str, compressed: bool) -> bytes:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    ds.SOPClassUID, ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7", sop_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = STUDY_UID, SERIES_UID
    ds.PatientName, ds.PatientID = "Synthetic^Test", "SYN-1"
    ds.StudyDate, ds.StudyDescription, ds.SeriesDescription = "20260914", "Synthetic study", "Synthetic series"
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = "OT", 1, 1 if compressed else 2
    ds.Rows = ds.Columns = 16
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.PixelRepresentation = 0
    gradient = np.arange(256, dtype=np.uint16).reshape(16, 16)
    if compressed:
        ds.BitsAllocated = ds.BitsStored = 8
        ds.HighBit = 7
        buf = io.BytesIO()
        Image.fromarray(gradient.astype(np.uint8)).save(buf, "JPEG", quality=95)
        ds.file_meta.TransferSyntaxUID = JPEGBaseline8Bit
        ds.PixelData = encapsulate([buf.getvalue()])
        ds["PixelData"].is_undefined_length = True
    else:
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.PixelData = (gradient * 100).tobytes()
    out = io.BytesIO()
    ds.save_as(out, enforce_file_format=True)
    return out.getvalue()


def login(client, email):
    client.cookies.clear()
    client.post("/api/v1/auth/register", params={"email": email, "password": "password123"})
    assert client.post("/api/v1/auth/login", data={"username": email, "password": "password123"}).status_code == 200


def upload(client, data):
    resp = client.post("/api/v1/medical-data/dicom/upload", files={"file": ("x.dcm", data, "application/dicom")})
    assert resp.status_code == 200, resp.text


def parse_multipart(resp):
    boundary = resp.headers["content-type"].split("boundary=")[1].strip()
    parts = []
    for chunk in resp.content.split(f"--{boundary}".encode())[1:-1]:
        head, _, body = chunk.partition(b"\r\n\r\n")
        parts.append((head.decode().strip(), body[:-2]))
    return parts


def test_qido_returns_dicom_json_only_when_requested(client):
    login(client, "ohif-json@example.com")
    jpeg_uid, raw_uid = generate_uid(), generate_uid()
    upload(client, make_dicom(jpeg_uid, compressed=True))
    upload(client, make_dicom(raw_uid, compressed=False))

    # HoloMed UI format is unchanged
    compact = client.get("/api/v1/dicomweb/studies").json()
    assert compact[0]["StudyInstanceUID"] == STUDY_UID and "0020000D" not in compact[0]

    resp = client.get("/api/v1/dicomweb/studies", headers=DICOM_JSON)
    assert resp.headers["content-type"].startswith("application/dicom+json")
    study = resp.json()[0]
    assert study["0020000D"] == {"vr": "UI", "Value": [STUDY_UID]}
    assert study["00100010"]["Value"][0]["Alphabetic"] == "Synthetic^Test"
    assert study["00081030"]["Value"] == ["Synthetic study"]
    assert study["00201206"]["Value"] == [1] and study["00201208"]["Value"] == [2]
    assert study["00080061"]["Value"] == ["OT"]
    # StudyInstanceUID filter
    assert client.get(f"/api/v1/dicomweb/studies?StudyInstanceUID={STUDY_UID}", headers=DICOM_JSON).json()
    assert client.get("/api/v1/dicomweb/studies?StudyInstanceUID=1.2.3", headers=DICOM_JSON).json() == []

    series = client.get(f"/api/v1/dicomweb/studies/{STUDY_UID}/series", headers=DICOM_JSON).json()
    assert series[0]["0020000E"]["Value"] == [SERIES_UID]          # was missing → OHIF requested series/null
    assert series[0]["0008103E"]["Value"] == ["Synthetic series"]
    assert series[0]["00201209"]["Value"] == [2]
    assert client.get(f"/api/v1/dicomweb/studies/{STUDY_UID}/series").json()[0]["SeriesInstanceUID"] == SERIES_UID

    instances = client.get(f"/api/v1/dicomweb/studies/{STUDY_UID}/series/{SERIES_UID}/instances",
                           headers=DICOM_JSON).json()
    assert {i["00080018"]["Value"][0] for i in instances} == {jpeg_uid, raw_uid}
    assert all(i["00280010"]["Value"] == [16] for i in instances)

    meta = client.get(f"/api/v1/dicomweb/studies/{STUDY_UID}/series/{SERIES_UID}/metadata").json()
    assert len(meta) == 2 and "7FE00010" not in meta[0]


def test_frames_endpoint_returns_pixel_data(client):
    login(client, "ohif-frames@example.com")
    jpeg_uid, raw_uid = generate_uid(), generate_uid()
    jpeg, raw = make_dicom(jpeg_uid, compressed=True), make_dicom(raw_uid, compressed=False)
    upload(client, jpeg)
    upload(client, raw)
    base = f"/api/v1/dicomweb/studies/{STUDY_UID}/series/{SERIES_UID}/instances"

    resp = client.get(f"{base}/{raw_uid}/frames/1")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("multipart/related")
    [(head, body)] = parse_multipart(resp)
    assert "application/octet-stream" in head and "transfer-syntax=1.2.840.10008.1.2.1" in head
    assert body == pydicom.dcmread(io.BytesIO(raw)).PixelData and len(body) == 16 * 16 * 2

    resp = client.get(f"{base}/{jpeg_uid}/frames/1")
    [(head, body)] = parse_multipart(resp)
    assert "image/jpeg" in head and "transfer-syntax=1.2.840.10008.1.2.4.50" in head
    assert body[:2] == b"\xff\xd8"                                     # JPEG SOI marker
    assert np.array(Image.open(io.BytesIO(body))).shape == (16, 16)
    assert 'type="image/jpeg"' in resp.headers["content-type"]

    assert client.get(f"{base}/{raw_uid}/frames/2").status_code == 404
    assert client.get(f"{base}/{raw_uid}/frames/x").status_code == 400
    assert client.get(f"{base}/1.2.3/frames/1").status_code == 404


def test_other_users_cannot_read_studies_or_frames(client):
    login(client, "ohif-owner@example.com")
    sop = generate_uid()
    upload(client, make_dicom(sop, compressed=False))
    login(client, "ohif-intruder@example.com")
    assert client.get("/api/v1/dicomweb/studies", headers=DICOM_JSON).json() == []
    assert client.get(f"/api/v1/dicomweb/studies/{STUDY_UID}/series", headers=DICOM_JSON).status_code == 404
    frames = f"/api/v1/dicomweb/studies/{STUDY_UID}/series/{SERIES_UID}/instances/{sop}/frames/1"
    assert client.get(frames).status_code == 404


# Not committed (licensing, see .gitignore); HOLOMED_REAL_CXR_DICOM can point at a local copy.
REAL_CXR = Path(os.getenv("HOLOMED_REAL_CXR_DICOM", Path(__file__).parent / "artifacts" / "real_cxr" / "source"
                          / "1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm"))


def test_upload_response_names_the_study_to_open(client):
    login(client, "ohif-upload@example.com")
    resp = client.post("/api/v1/medical-data/dicom/upload",
                       files={"file": ("x.dcm", make_dicom(generate_uid(), compressed=True), "application/dicom")})
    assert resp.status_code == 200
    assert resp.json()["study_instance_uid"] == STUDY_UID


@pytest.mark.skipif(not REAL_CXR.exists(), reason="de-identified SIIM chest X-ray DICOM not present locally")
def test_uploaded_real_cxr_is_retrievable_by_ohif(client):
    login(client, "ohif-cxr@example.com")
    source = pydicom.dcmread(REAL_CXR)
    resp = client.post("/api/v1/medical-data/dicom/upload",
                       files={"file": ("cxr.dcm", REAL_CXR.read_bytes(), "application/dicom")})
    assert resp.status_code == 200, resp.text
    study_uid = resp.json()["study_instance_uid"]
    assert study_uid == source.StudyInstanceUID

    studies = client.get("/api/v1/dicomweb/studies", params={"StudyInstanceUID": study_uid}, headers=DICOM_JSON).json()
    assert [s["0020000D"]["Value"][0] for s in studies] == [study_uid]
    series = client.get(f"/api/v1/dicomweb/studies/{study_uid}/series", headers=DICOM_JSON).json()
    series_uid = series[0]["0020000E"]["Value"][0]
    assert series_uid == source.SeriesInstanceUID

    meta = client.get(f"/api/v1/dicomweb/studies/{study_uid}/series/{series_uid}/metadata").json()
    assert len(meta) == 1
    assert meta[0]["00080018"]["Value"] == [source.SOPInstanceUID]
    assert meta[0]["00280010"]["Value"] == [1024] and meta[0]["00280011"]["Value"] == [1024]
    assert meta[0]["00280004"]["Value"] == ["MONOCHROME2"]

    frames = client.get(f"/api/v1/dicomweb/studies/{study_uid}/series/{series_uid}"
                        f"/instances/{source.SOPInstanceUID}/frames/1")
    assert frames.status_code == 200
    (head, body), = parse_multipart(frames)
    assert "image/jpeg" in head and "transfer-syntax=1.2.840.10008.1.2.4.50" in head
    image = Image.open(io.BytesIO(body))
    assert image.size == (1024, 1024)
    assert len(image.convert("L").getcolors(256)) > 100
