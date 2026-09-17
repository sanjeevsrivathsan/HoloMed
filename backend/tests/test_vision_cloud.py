"""Phase 5: cloud vision provider, private worker contract, provider status.

The worker is exercised in-process (same code that runs on Modal); the cloud
provider is pointed at it through an httpx transport, so the full
backend → provider → worker → model path is tested without network access.
"""
import json
import logging
import os

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from backend import config
from backend.database import get_session
from backend.dependencies.auth import get_current_user
from backend.models import User
from backend.routers import vision as vision_router
from backend.services.vision import cloud, constants, inference, provider, results
from backend.services.vision.errors import (InvalidImageError, UnknownTargetError, UnsupportedImageError,
                                            VisionProviderUnavailable)
from backend.services.vision.schemas import SAFETY_MESSAGE, VisionScreenResponse
from backend.vision_worker.app import create_app

_REAL_HTTPX_CLIENT = httpx.Client  # captured before tests patch httpx.Client

HERE = os.path.dirname(__file__)
NIH_PNG = os.path.join(HERE, "artifacts", "real_cxr", "source", "00000001_000.png")
TOKEN = "test-worker-token-7f3c9a"
CLOUD_URL = "https://vision-worker.test"

pytestmark = pytest.mark.skipif(not os.path.isfile(config.VISION_WEIGHTS_PATH),
                                reason="validated local vision checkpoint not present")
needs_nih = pytest.mark.skipif(not os.path.isfile(NIH_PNG), reason="NIH sample not present")


def read(path):
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(config, "VISION_WORKER_TOKEN", TOKEN)
    monkeypatch.setattr(config, "VISION_PRELOAD", False)
    return TestClient(create_app())


@pytest.fixture
def cloud_env(monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    monkeypatch.setattr(config, "VISION_CLOUD_URL", CLOUD_URL)
    monkeypatch.setattr(config, "VISION_CLOUD_TOKEN", TOKEN)


def route_cloud(monkeypatch, handler):
    """Make CloudVisionProvider's httpx.Client use ``handler`` as its transport."""
    real_client = _REAL_HTTPX_CLIENT
    seen = []

    def recording(request):
        seen.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(recording)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(cloud.httpx, "Client", factory)
    return seen


def forward_to(worker_client):
    def handler(request: httpx.Request) -> httpx.Response:
        resp = worker_client.request(request.method, request.url.path,
                                     headers={k: v for k, v in request.headers.items() if k != "host"},
                                     content=request.content)
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)
    return handler


# ── worker ────────────────────────────────────────────────────────────────
def test_worker_requires_token(worker, monkeypatch):
    assert worker.get("/v1/health").status_code == 401
    assert worker.get("/v1/health", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert worker.post("/v1/screen", files={"file": ("u", b"x")}).status_code == 401
    monkeypatch.setattr(config, "VISION_WORKER_TOKEN", "")
    assert worker.get("/v1/health", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 503


def test_worker_has_no_public_docs(worker):
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert worker.get(path).status_code == 404


@needs_nih
def test_worker_screen_matches_local(worker):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    resp = worker.post("/v1/screen", headers=auth, files={"file": ("upload", read(NIH_PNG))})
    assert resp.status_code == 200
    remote = VisionScreenResponse.model_validate(resp.json())
    local = inference.screen_image(read(NIH_PNG))
    assert [(f.pathology, round(f.score, 6)) for f in remote.findings] == \
           [(f.pathology, round(f.score, 6)) for f in local.findings]
    assert remote.primary_finding.pathology == "Cardiomegaly"
    assert remote.model.weight_sha256 == constants.EXPECTED_SHA256
    health = worker.get("/v1/health", headers=auth).json()
    assert health == {"status": "ready", "model_ready": True}


def test_worker_error_mapping(worker):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert worker.post("/v1/screen", headers=auth, files={"file": ("u", b"plain text")}).status_code == 415
    assert worker.post("/v1/screen", headers=auth,
                       files={"file": ("u", b"\x89PNG\r\n\x1a\n" + b"\0" * 20)}).status_code == 400
    assert worker.post("/v1/screen", headers=auth, files={"file": ("u", b"")}).status_code == 400


# ── cloud provider contract ───────────────────────────────────────────────
@needs_nih
def test_cloud_request_is_minimal_and_authenticated(cloud_env, worker, monkeypatch):
    seen = route_cloud(monkeypatch, forward_to(worker))
    result = provider.get_vision_provider().screen(read(NIH_PNG), "Effusion")
    assert result.explanation.target_pathology == "Effusion"
    req = seen[0]
    assert str(req.url) == f"{CLOUD_URL}/v1/screen"
    assert req.headers["authorization"] == f"Bearer {TOKEN}"
    body = req.content
    assert b'filename="upload"' in body and b"00000001_000" not in body
    assert b'name="target"\r\n\r\nEffusion' in body
    # only two form parts: the image and the target
    assert body.count(b"Content-Disposition") == 2
    assert result.safety.message == SAFETY_MESSAGE and result.result_id is None


@needs_nih
def test_cloud_response_validation_rejects_tampering(cloud_env, worker, monkeypatch):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    good = worker.post("/v1/screen", headers=auth, files={"file": ("upload", read(NIH_PNG))}).json()
    assert cloud.validate_worker_response(good).primary_finding.pathology == "Cardiomegaly"

    def tampered(mutate):
        payload = json.loads(json.dumps(good))
        mutate(payload)
        return payload

    bad_payloads = [
        tampered(lambda p: p["model"].update(weight_sha256="0" * 64)),
        tampered(lambda p: p["model"].update(weights="imagenet-resnet")),
        tampered(lambda p: p["findings"].pop()),
        tampered(lambda p: p["findings"].__setitem__(0, {"pathology": "Normal", "score": 1.0})),
        tampered(lambda p: p["primary_finding"].update(pathology="Hernia")),
        tampered(lambda p: p["explanation"].update(target_layer="features.norm5")),
        tampered(lambda p: p["explanation"].update(target_score=0.1234)),
        tampered(lambda p: p.pop("explanation")),
        {"detail": "not a result"},
        [],
    ]
    for payload in bad_payloads:
        with pytest.raises(VisionProviderUnavailable):
            cloud.validate_worker_response(payload)
    # safety text is always the backend's own
    spoofed = tampered(lambda p: p["safety"].update(message="Diagnosis confirmed.", requires_clinical_review=False))
    fixed = cloud.validate_worker_response(spoofed)
    assert fixed.safety.message == SAFETY_MESSAGE and fixed.safety.requires_clinical_review


@pytest.mark.parametrize("status,body,exc", [
    (400, {"detail": "Could not decode PNG image"}, InvalidImageError),
    (415, {"detail": "Unsupported file type."}, UnsupportedImageError),
    (422, {"detail": "Unsupported DICOM modality 'CT'"}, UnsupportedImageError),
    (422, {"detail": "Unknown target pathology 'X'"}, UnknownTargetError),
    (413, {"detail": "File too large"}, UnsupportedImageError),
    (401, {"detail": "Unauthorized"}, VisionProviderUnavailable),
    (500, {"detail": "boom"}, VisionProviderUnavailable),
    (503, {"detail": "Vision model is not available"}, VisionProviderUnavailable),
    (200, None, VisionProviderUnavailable),  # non-JSON
    (200, {"unexpected": True}, VisionProviderUnavailable),
])
def test_cloud_status_mapping(cloud_env, monkeypatch, status, body, exc):
    def handler(request):
        if body is None:
            return httpx.Response(status, content=b"<html>not json</html>")
        return httpx.Response(status, json=body)
    route_cloud(monkeypatch, handler)
    with pytest.raises(exc):
        provider.get_vision_provider().screen(b"\x89PNG....")


@pytest.mark.parametrize("error", [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("c")])
def test_cloud_network_failures(cloud_env, monkeypatch, error):
    def handler(request):
        raise error
    route_cloud(monkeypatch, handler)
    with pytest.raises(VisionProviderUnavailable):
        provider.get_vision_provider().screen(b"data")


@pytest.mark.parametrize("url,token", [("", TOKEN), (CLOUD_URL, ""), ("http://vision.example.com", TOKEN)])
def test_cloud_misconfiguration_is_controlled(cloud_env, monkeypatch, url, token):
    monkeypatch.setattr(config, "VISION_CLOUD_URL", url)
    monkeypatch.setattr(config, "VISION_CLOUD_TOKEN", token)
    seen = route_cloud(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(VisionProviderUnavailable):
        provider.get_vision_provider().screen(b"data")
    assert seen == []
    assert provider.get_vision_provider().status() == {"configured": False, "model_ready": False, "accelerator": None}


def test_cloud_failure_never_falls_back_to_local(cloud_env, monkeypatch):
    def local_must_not_run(*a, **k):
        raise AssertionError("local inference used while VISION_PROVIDER=cloud")
    monkeypatch.setattr(inference, "screen_image", local_must_not_run)
    route_cloud(monkeypatch, lambda r: httpx.Response(503, json={"detail": "down"}))
    with pytest.raises(VisionProviderUnavailable):
        provider.get_vision_provider().screen(b"data")


def test_cloud_token_never_logged(cloud_env, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    route_cloud(monkeypatch, lambda r: httpx.Response(401, json={"detail": "Unauthorized"}))
    with pytest.raises(VisionProviderUnavailable) as exc_info:
        provider.get_vision_provider().screen(b"data")
    assert TOKEN not in caplog.text
    assert TOKEN not in str(exc_info.value)


def test_cloud_status_reports_remote_readiness(cloud_env, monkeypatch):
    route_cloud(monkeypatch, lambda r: httpx.Response(200, json={"status": "ready", "model_ready": True}))
    assert provider.get_vision_provider().status() == {"configured": True, "model_ready": True, "reachable": True, "accelerator": "gpu"}
    route_cloud(monkeypatch, lambda r: httpx.Response(200, json={"status": "loading", "model_ready": False}))
    assert provider.get_vision_provider().status() == {"configured": True, "model_ready": False, "reachable": True, "accelerator": "gpu"}
    route_cloud(monkeypatch, lambda r: httpx.Response(401, json={}))
    assert provider.get_vision_provider().status() == {"configured": True, "model_ready": False, "reachable": False, "accelerator": "gpu"}

    def down(request):
        raise httpx.ConnectError("refused")
    route_cloud(monkeypatch, down)
    assert provider.get_vision_provider().status()["reachable"] is False


# ── backend API with the cloud provider ───────────────────────────────────
@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        user = User(email="cloud@example.com", hashed_password="x")
        s.add(user)
        s.commit()
        s.refresh(user)
        user_id = user.id

    def session_override():
        with Session(engine) as s:
            yield s

    app = FastAPI()
    app.include_router(vision_router.router)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(id=user_id, email="cloud@example.com")
    monkeypatch.setattr(vision_router, "_status_cache", {"at": 0.0, "value": None})
    results.clear()
    return TestClient(app)


@needs_nih
def test_api_end_to_end_via_cloud_provider(api, cloud_env, worker, monkeypatch):
    route_cloud(monkeypatch, forward_to(worker))
    resp = api.post("/api/v1/vision/screen", files={"file": ("patient_scan.png", read(NIH_PNG), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["primary_finding"]["pathology"] == "Cardiomegaly"
    assert round(body["primary_finding"]["score"], 4) == 0.66
    assert len(body["findings"]) == 18 and body["result_id"]
    assert "patient_scan" not in resp.text
    status = api.get("/api/v1/vision/status").json()
    assert status == {"provider": "cloud", "provider_configured": True, "model_ready": True, "accelerator": "gpu",
                      "status": "ready"}
    assert TOKEN not in json.dumps(status) and "vision-worker" not in json.dumps(status)


def test_api_cloud_outage_is_controlled_503(api, cloud_env, monkeypatch):
    route_cloud(monkeypatch, lambda r: httpx.Response(502, text="Bad Gateway from upstream infra"))
    resp = api.post("/api/v1/vision/screen", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Vision service is not available"}
    status = api.get("/api/v1/vision/status").json()
    assert status["status"] == "unavailable" and status["model_ready"] is False


def test_api_status_unconfigured_cloud(api, monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    monkeypatch.setattr(config, "VISION_CLOUD_URL", "")
    assert api.get("/api/v1/vision/status").json() == {
        "provider": "cloud", "provider_configured": False, "model_ready": False, "accelerator": None,
        "status": "unavailable"}


def test_api_status_local(api, monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "local")
    body = api.get("/api/v1/vision/status").json()
    assert body["provider"] == "local" and body["provider_configured"] is True
    assert body["status"] in ("ready", "standby", "loading")
