import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from backend.main import app
from backend.database import get_session
from backend.models.user import User

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

def get_session_override():
    with Session(engine) as session:
        yield session

@pytest.fixture(name="db_session", autouse=True)
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture():
    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

def test_successful_registration(client: TestClient, db_session: Session):
    response = client.post("/api/v1/auth/register", params={"email": "newuser@example.com", "password": "SecurePassword123!"})
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["email"] == "newuser@example.com"
    
    # Verify password hashing
    user = db_session.exec(select(User).where(User.email == "newuser@example.com")).first()
    assert user is not None
    assert user.hashed_password is not None
    assert user.hashed_password != "SecurePassword123!"

def test_duplicate_email_rejection(client: TestClient):
    client.post("/api/v1/auth/register", params={"email": "dup@example.com", "password": "SecurePassword123!"})
    response = client.post("/api/v1/auth/register", params={"email": "dup@example.com", "password": "AnotherPassword456!"})
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"].lower()

def test_invalid_registration_data(client: TestClient):
    # Short password
    response = client.post("/api/v1/auth/register", params={"email": "short@example.com", "password": "short"})
    assert response.status_code == 400
    assert "password must be at least 8 characters" in response.json()["detail"].lower()

    # Missing fields
    response = client.post("/api/v1/auth/register", params={"email": "missing@example.com"})
    assert response.status_code == 422 # FastAPI validation error for missing query param
