import os
import sys
import uuid
import httpx
import tempfile
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

BASE_URL = "http://127.0.0.1:8002"

def create_minimal_dicom_bytes():
    ds = Dataset()
    ds.SOPClassUID = generate_uid()
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = 'OT'
    ds.PatientName = 'Test^Smoke'
    ds.PatientID = 'SMK123'
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
    import io
    buffer = io.BytesIO()
    ds.save_as(buffer, write_like_original=False)
    return buffer.getvalue()

def run_smoke_test():
    client = httpx.Client(base_url=BASE_URL)
    
    # 1. GET /api/v1/ready
    print("Testing GET /api/v1/ready...")
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 200, f"Health failed: {resp.text}"
    print("OK")
    
    # 2. Register & Login
    print("Testing POST /api/v1/auth/login...")
    email = f"smoke_{uuid.uuid4().hex[:8]}@example.com"
    password = "SmokeTest123!"
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    print("OK")
    
    # 3. GET /api/v1/auth/me
    print("Testing GET /api/v1/auth/me...")
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200, f"Me failed: {resp.text}"
    assert resp.json()["email"] == email
    print("OK")
    
    # 4. GET /api/v1/medical-data/patients
    print("Testing GET /api/v1/medical-data/patients...")
    resp = client.get("/api/v1/medical-data/patients")
    assert resp.status_code == 200, f"Patients failed: {resp.text}"
    print("OK")
    
    # 5. POST /api/v1/medical-data/dicom/upload
    print("Testing POST /api/v1/medical-data/dicom/upload...")
    dicom_bytes = create_minimal_dicom_bytes()
    files = {"file": ("smoke.dcm", dicom_bytes, "application/dicom")}
    resp = client.post("/api/v1/medical-data/dicom/upload", files=files)
    assert resp.status_code == 200, f"Upload failed: {resp.text}"
    instance_id = resp.json()["instance_id"]
    print("OK")
    
    # 6. GET /api/v1/dicomweb/studies
    print("Testing GET /api/v1/dicomweb/studies...")
    resp = client.get("/api/v1/dicomweb/studies")
    assert resp.status_code == 200, f"QIDO list failed: {resp.text}"
    print("OK")
    
    # 7. GET /api/v1/medical-data/instances/{instance_id}/download
    print(f"Testing GET /api/v1/medical-data/instances/{instance_id}/download...")
    resp = client.get(f"/api/v1/medical-data/instances/{instance_id}/download")
    assert resp.status_code == 200, f"Download failed: {resp.text}"
    assert len(resp.content) == len(dicom_bytes)
    print("OK")
    
    print("\nALL SMOKE TESTS PASSED!")

if __name__ == "__main__":
    run_smoke_test()
