import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json

from backend.main import app
from backend.database import get_session
from backend.models import User, AuditLog
from backend.services.auth_service import get_password_hash

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


def test_get_audit_logs_unauthenticated(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    client.cookies.clear()
    response = client.get("/api/v1/audit")
    assert response.status_code == 401


def test_get_audit_logs_authenticated(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "audit_test@example.com"
    password = "password123"
    
    # 1. Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    response = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    
    # Add a mock audit log explicitly
    with Session(engine) as session:
        from sqlmodel import select
        user = session.exec(select(User).where(User.email == email)).first()
        log = AuditLog(
            user_id=user.id,
            action="test_action",
            details=json.dumps({"key": "value"})
        )
        session.add(log)
        session.commit()
    
    # 2. Test GET /audit
    response = client.get("/api/v1/audit")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    
    # Check that our test log is returned
    found = any(log["action"] == "test_action" for log in data)
    assert found
