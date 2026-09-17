import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json

from backend.main import app
from backend.database import get_session
from backend.models import User, Patient

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

def test_consent_and_storage_crud(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "cs_test@example.com"
    password = "password123"
    
    # 1. Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    client.post("/api/v1/auth/login", data={"username": email, "password": password})
    
    # Create patient for test
    with Session(engine) as session:
        from sqlmodel import select
        user = session.exec(select(User).where(User.email == email)).first()
        patient = Patient(owner_id=user.id, display_name="CS Test Patient")
        session.add(patient)
        session.commit()
        patient_id = patient.id
        
    # --- Consents ---
    cons_data = {
        "patient_id": patient_id,
        "recipient": "Dr. Smith",
        "purpose": "Consultation",
        "scope": "Reports",
        "issued_date": "2026-01-01",
        "expiry_date": "2027-01-01"
    }
    response = client.post("/api/v1/consents", json=cons_data)
    assert response.status_code == 200
    cons = response.json()
    cons_id = cons["id"]
    
    response = client.put(f"/api/v1/consents/{cons_id}/revoke")
    assert response.status_code == 200
    assert response.json()["revoked"] == True
    
    response = client.get("/api/v1/consents")
    assert response.status_code == 200
    assert len(response.json()) == 1
    
    response = client.delete(f"/api/v1/consents/{cons_id}")
    assert response.status_code == 200
    
    # --- Storage Connections ---
    conn_data = {
        "provider": "google_drive",
        "label": "My Drive",
        "status": "connected"
    }
    response = client.post("/api/v1/storage-connections", json=conn_data)
    assert response.status_code == 200
    conn = response.json()
    conn_id = conn["id"]
    
    conn_data["label"] = "Updated Drive"
    response = client.put(f"/api/v1/storage-connections/{conn_id}", json=conn_data)
    assert response.status_code == 200
    assert response.json()["label"] == "Updated Drive"
    
    response = client.get("/api/v1/storage-connections")
    assert response.status_code == 200
    assert len(response.json()) == 1
    
    response = client.delete(f"/api/v1/storage-connections/{conn_id}")
    assert response.status_code == 200
