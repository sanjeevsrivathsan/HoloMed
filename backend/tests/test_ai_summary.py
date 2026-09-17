import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json

from backend.main import app
from backend.database import get_session
from datetime import date

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

def test_report_summary(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "ai_test@example.com"
    password = "password123"
    
    # Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    client.post("/api/v1/auth/login", data={"username": email, "password": password})
    
    # Create patient, a report whose values were confirmed, and one canonical measurement
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
            type="Blood Test",
            status="confirmed",
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=100,
            storage_key="test"
        )
        session.add(report)
        session.commit()
        report_id = report.id
        session.add(MedicalMeasurement(test_name="HbA1c", value=5.4, unit="%", report_date=date(2026, 8, 25),
                                       report_id=report_id, patient_id=patient.id, owner_id=user.id))
        session.commit()

    # Summaries go through the configured text AI provider (mocked here)
    from backend.services.explanation import report_summary
    from backend.services.text_ai.providers import Completion

    class MockProvider:
        name, model = "mock", "mock-model"

        def complete_json(self, system, user, schema, max_tokens, temperature):
            return Completion(text=json.dumps({
                "overview": "This blood test report lists an HbA1c result.",
                "terms": ["HbA1c: a blood test that reflects average blood sugar over recent months."],
                "questions": ["What does this result mean for me?"],
            }), model=self.model)

    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: MockProvider())
    response = client.post(f"/api/v1/reports/{report_id}/summary", data={"mode": "standard"})

    assert response.status_code == 200
    summary = response.json()
    assert summary["mode"] == "standard"
    assert summary["report_id"] == report_id
    assert summary["safety_message"].startswith("AI-generated information")
    sections = json.loads(summary["sections"])
    assert sections[0] == {"key": "executive", "label": "Overview",
                           "content": "This blood test report lists an HbA1c result.", "visible": True}

    # Get summary
    response = client.get(f"/api/v1/reports/{report_id}/summary")
    assert response.status_code == 200
    assert response.json()["mode"] == "standard"
