import io
import uuid
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from sqlmodel import select

from backend.main import app
from backend.database import get_session
from backend.models.user import User
from backend.models.study import Study
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import pytest

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

def create_minimal_dicom_bytes():
    ds = Dataset()
    ds.SOPClassUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = 'OT'
    ds.PatientName = 'Test^Patient'
    ds.PatientID = '12345'
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    file_meta = FileMetaDataset()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = file_meta
    ds.Rows = 1
    ds.Columns = 1
    ds.BitsAllocated = 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.PixelData = b'\x00'
    buffer = io.BytesIO()
    ds.save_as(buffer, write_like_original=False)
    return buffer.getvalue()

def test_dicomweb_study_endpoint(client: TestClient):
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPass123!"
    # Register
    resp = client.post("/api/v1/auth/register", params={"email": email, "password": password})
    assert resp.status_code == 201
    # Login
    resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200
    # Upload DICOM
    dicom_bytes = create_minimal_dicom_bytes()
    files = {"file": ("test.dcm", dicom_bytes, "application/dicom")}
    resp = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert resp.status_code == 200
    # Retrieve the created study UID from DB
    with Session(engine) as session:
        user: User = session.exec(select(User).where(User.email == email)).first()
        study = session.exec(select(Study).where(Study.owner_id == user.id)).first()
        assert study is not None
        study_instance_uid = study.study_instance_uid
    # Query DICOMweb study endpoint
    resp = client.get(f"/api/v1/dicomweb/studies/{study_instance_uid}")
    assert resp.status_code == 200
    json_body = resp.json()
    assert json_body["StudyInstanceUID"] == study_instance_uid
