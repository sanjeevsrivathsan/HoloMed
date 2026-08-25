import io
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from backend.main import app
from backend.database import get_session
from sqlalchemy.pool import StaticPool
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid
import uuid

# Setup an in-memory SQLite DB for tests
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

def get_session_override():
    with Session(engine) as session:
        yield session

@pytest.fixture(name="client")
def client_fixture():
    SQLModel.metadata.create_all(engine)
    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)

def create_dummy_dicom(size_bytes: int = 100) -> bytes:
    file_meta = Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3"
    file_meta.ImplementationClassUID = "1.2.3.4"

    ds = FileDataset(None, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = "Test^Patient"
    ds.PatientID = "123456"
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.is_little_endian = True
    ds.is_implicit_VR = True

    # Add dummy pixel data to pad size
    if size_bytes > 0:
        ds.PixelData = b"0" * size_bytes

    out = io.BytesIO()
    ds.save_as(out)
    return out.getvalue()

def test_create_patient(client: TestClient):
    response = client.post("/api/v1/medical-data/patients", json={
        "display_name": "Test Patient",
        "external_id": "EXT-123"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Test Patient"
    assert data["external_id"] == "EXT-123"
    assert "id" in data

def test_list_patients(client: TestClient):
    client.post("/api/v1/medical-data/patients", json={"display_name": "Patient 1"})
    response = client.get("/api/v1/medical-data/patients")
    assert response.status_code == 200
    assert len(response.json()) >= 1

def test_upload_dicom_valid(client: TestClient):
    dicom_bytes = create_dummy_dicom()
    files = {"file": ("test.dcm", dicom_bytes, "application/dicom")}
    response = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert response.status_code == 200
    assert "instance_id" in response.json()

def test_upload_dicom_invalid(client: TestClient):
    files = {"file": ("test.txt", b"not a dicom", "text/plain")}
    response = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert response.status_code == 400
    assert "Invalid DICOM file" in response.json()["detail"]

def test_upload_dicom_too_large(client: TestClient):
    # 51 MiB file simulation
    # Actually allocating 51MB might crash pytest or take too long,
    # so we can just mock the size limit check if possible, or create a big byte array.
    # To be safe and quick, we just send a large byte payload.
    large_bytes = b"0" * (50 * 1024 * 1024 + 1)
    files = {"file": ("test.dcm", large_bytes, "application/dicom")}
    response = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert response.status_code == 413
    assert "File too large" in response.json()["detail"]

def test_download_instance(client: TestClient):
    dicom_bytes = create_dummy_dicom()
    files = {"file": ("test.dcm", dicom_bytes, "application/dicom")}
    upload_resp = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert upload_resp.status_code == 200
    instance_id = upload_resp.json()["instance_id"]

    download_resp = client.get(f"/api/v1/medical-data/instances/{instance_id}/download")
    assert download_resp.status_code == 200
    assert len(download_resp.content) > 0
