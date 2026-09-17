import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json

from backend.main import app
from backend.database import get_session
from backend.models import User, Patient, Report

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

def test_report_summary(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "ai_test@example.com"
    password = "password123"
    
    # Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    client.post("/api/v1/auth/login", data={"username": email, "password": password})
    
    # Create patient & report
    with Session(engine) as session:
        from sqlmodel import select
        user = session.exec(select(User).where(User.email == email)).first()
        patient = Patient(owner_id=user.id, display_name="AI Test Patient")
        session.add(patient)
        session.commit()
        
        report = Report(
            owner_id=user.id,
            patient_id=patient.id,
            title="Test Report",
            type="Other",
            original_filename="test.txt",
            mime_type="text/plain",
            file_size=100,
            storage_key="test"
        )
        session.add(report)
        session.commit()
        report_id = report.id
        
    # Generate summary with mocked httpx post for Ollama
    from unittest.mock import patch, AsyncMock
    import httpx
    
    mock_response = httpx.Response(200, json={
        "response": json.dumps([{"key": "executive", "label": "Executive Summary", "content": "Test summary", "visible": True}])
    }, request=httpx.Request("POST", "http://test"))
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        response = client.post(f"/api/v1/reports/{report_id}/summary", data={"mode": "standard"})

    assert response.status_code == 200
    summary = response.json()
    assert summary["mode"] == "standard"
    assert summary["report_id"] == report_id
    
    # Get summary
    response = client.get(f"/api/v1/reports/{report_id}/summary")
    assert response.status_code == 200
    assert response.json()["mode"] == "standard"
