import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
import json

from backend.main import app
from backend.database import get_session
from backend.models import User, Template

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

def test_template_crud(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")
    email = "template_test@example.com"
    password = "password123"
    
    # 1. Register and login
    client.post("/api/v1/auth/register", params={"email": email, "password": password})
    client.post("/api/v1/auth/login", data={"username": email, "password": password})
    
    # 2. Create template
    tmpl_data = {
        "name": "Test Template",
        "category": "Patient",
        "description": "Test Desc",
        "sections": json.dumps([{"id": "s1", "label": "Label 1", "order": 1, "visible": True}])
    }
    response = client.post("/api/v1/templates", json=tmpl_data)
    assert response.status_code == 200
    tmpl = response.json()
    assert tmpl["name"] == "Test Template"
    tmpl_id = tmpl["id"]
    
    # 3. Get template
    response = client.get(f"/api/v1/templates/{tmpl_id}")
    assert response.status_code == 200
    assert response.json()["id"] == tmpl_id
    
    # 4. Update template
    tmpl_data["name"] = "Updated Template"
    response = client.put(f"/api/v1/templates/{tmpl_id}", json=tmpl_data)
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Template"
    
    # 5. List templates
    response = client.get("/api/v1/templates")
    assert response.status_code == 200
    assert len(response.json()) == 1
    
    # 6. Delete template
    response = client.delete(f"/api/v1/templates/{tmpl_id}")
    assert response.status_code == 200
    
    response = client.get(f"/api/v1/templates/{tmpl_id}")
    assert response.status_code == 404
