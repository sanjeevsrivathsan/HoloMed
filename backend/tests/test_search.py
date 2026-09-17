import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json
from datetime import date

from backend.main import app
from backend.database import get_session
from backend.models import User, Patient, Report, MedicalMeasurement

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

def test_search(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "search_test@example.com"
    password = "password123"
    
    # Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    client.post("/api/v1/auth/login", data={"username": email, "password": password})
    
    # Create patient, report, measurement
    with Session(engine) as session:
        from sqlmodel import select
        user = session.exec(select(User).where(User.email == email)).first()
        patient = Patient(owner_id=user.id, display_name="Search Test Patient")
        session.add(patient)
        session.commit()
        
        report = Report(
            owner_id=user.id,
            patient_id=patient.id,
            title="HbA1c Blood Test Results",
            type="Blood Test",
            original_filename="test.txt",
            mime_type="text/plain",
            file_size=100,
            storage_key="test"
        )
        session.add(report)
        
        meas = MedicalMeasurement(
            patient_id=patient.id,
            owner_id=user.id,
            test_name="HbA1c",
            value=8.5,
            unit="%",
            flag="abnormal",
            report_date=date(2026, 8, 25)
        )
        session.add(meas)
        session.commit()
        
    # Search for HbA1c
    response = client.post("/api/v1/search", json={"query": "HbA1c"})
    assert response.status_code == 200
    res = response.json()
    
    assert len(res["report_ids"]) == 1
    assert len(res["measurement_ids"]) == 1
