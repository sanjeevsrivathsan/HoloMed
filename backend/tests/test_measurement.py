import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from datetime import date

from backend.main import app
from backend.database import get_session
from backend.models import User, Patient, MedicalMeasurement

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

def test_measurement_crud(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "measurement_test@example.com"
    password = "password123"
    
    # 1. Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    
    # Create patient for test
    with Session(engine) as session:
        from sqlmodel import select
        user = session.exec(select(User).where(User.email == email)).first()
        patient = Patient(owner_id=user.id, display_name="Measurement Test Patient")
        session.add(patient)
        session.commit()
        patient_id = patient.id

    # 2. Create measurement
    meas_data = {
        "patient_id": patient_id,
        "test_name": "HbA1c",
        "value": 5.9,
        "unit": "%",
        "report_date": "2026-08-25"
    }
    response = client.post("/api/v1/measurements", json=meas_data)
    assert response.status_code == 200
    meas = response.json()
    assert meas["test_name"] == "HbA1c"
    assert meas["value"] == 5.9
    meas_id = meas["id"]
    
    # 3. Get measurement
    response = client.get(f"/api/v1/measurements/{meas_id}")
    assert response.status_code == 200
    assert response.json()["id"] == meas_id
    
    # 4. List measurements
    response = client.get("/api/v1/measurements")
    assert response.status_code == 200
    assert len(response.json()) == 1
    
    # 5. Delete measurement
    response = client.delete(f"/api/v1/measurements/{meas_id}")
    assert response.status_code == 200
    
    response = client.get(f"/api/v1/measurements/{meas_id}")
    assert response.status_code == 404
