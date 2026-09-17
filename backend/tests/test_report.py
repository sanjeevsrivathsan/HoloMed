import io
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select, Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import get_session
from backend.models.user import User
from backend.models.report import Report
from backend.models.audit_log import AuditLog

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


def test_unauthenticated_report_creation(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    client.cookies.clear()
    files = {"file": ("test_report.pdf", b"%PDF-1.4...", "application/pdf")}
    resp = client.post("/api/v1/reports", files=files)
    assert resp.status_code == 401


def test_authenticated_report_workflow(client: TestClient):
    # Register and Login User 1
    email1 = f"user1_{uuid.uuid4().hex[:8]}@example.com"
    password = "StrongPassword123!"
    resp = client.post("/api/v1/auth/register", params={"email": email1, "password": password})
    assert resp.status_code == 201
    resp = client.post("/api/v1/auth/login", data={"username": email1, "password": password})
    assert resp.status_code == 200

    # 1. Authenticated report creation
    pdf_content = b"%PDF-1.4\nTest PDF content..."
    files = {"file": ("test_report.pdf", pdf_content, "application/pdf")}
    data = {"title": "My Blood Test", "type": "Blood Test", "hospital": "General Hospital"}
    
    resp = client.post("/api/v1/reports", files=files, data=data)
    assert resp.status_code == 200, resp.text
    report_json = resp.json()
    print("REPORT JSON:", report_json)
    assert report_json["title"] == "My Blood Test"
    assert report_json["type"] == "Blood Test"
    report_id = report_json["id"]
    
    # 8. Uploaded file persistence/retrieval
    # 5. Report retrieval (metadata)
    resp = client.get(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == report_id
    
    # Report retrieval (download)
    resp = client.get(f"/api/v1/reports/{report_id}/download")
    assert resp.status_code == 200
    assert resp.content == pdf_content
    
    # 3. Report listing
    resp = client.get("/api/v1/reports")
    assert resp.status_code == 200
    reports_list = resp.json()
    assert len(reports_list) == 1
    assert reports_list[0]["id"] == report_id

    # 9. Audit event creation
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == email1)).first()
        logs = session.exec(select(AuditLog).where(AuditLog.user_id == user.id)).all()
        actions = [log.action for log in logs]
        assert "report_uploaded" in actions
        assert "report_downloaded" in actions

    # Register and Login User 2
    email2 = f"user2_{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/v1/auth/register", params={"email": email2, "password": password})
    client.post("/api/v1/auth/login", data={"username": email2, "password": password})

    # 4. Ownership isolation
    # User 2 tries to access User 1's report
    resp = client.get(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 404
    
    resp = client.get(f"/api/v1/reports/{report_id}/download")
    assert resp.status_code == 404
    
    resp = client.delete(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 404

    # User 2 lists reports (should be empty)
    resp = client.get("/api/v1/reports")
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # 6. Invalid report ID
    resp = client.get("/api/v1/reports/999999")
    assert resp.status_code == 404

    # Login User 1 again
    client.post("/api/v1/auth/login", data={"username": email1, "password": password})
    
    # 7. Report deletion
    resp = client.delete(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 200
    
    # Ensure it's deleted
    resp = client.get(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 404
    
    # Audit log check for deletion
    with Session(engine) as session:
        logs = session.exec(select(AuditLog).where(AuditLog.user_id == user.id)).all()
        actions = [log.action for log in logs]
        assert "report_deleted" in actions
