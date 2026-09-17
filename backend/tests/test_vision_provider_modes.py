"""Deployment modes: local vision is the primary/default provider; cloud is optional.

- local works with no cloud settings and no network access
- cloud must be selected explicitly and fails with a controlled 503 (no fallback)
- the status endpoint reports provider + accelerator without secrets or paths
- the Modal image ships every backend module the worker imports
"""
import json
import os
import pathlib
import socket
import subprocess
import sys

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
from backend.services.vision import cloud, inference, provider, results
from backend.services.vision.constants import EXPECTED_TARGETS

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent.parent
NIH_PNG = HERE / "artifacts" / "real_cxr" / "source" / "00000001_000.png"
SENTINEL_TOKEN = "sentinel-cloud-token-do-not-leak-91c2"
SENTINEL_URL = "https://internal-worker-sentinel.example.net"

_REAL_HTTPX_CLIENT = httpx.Client  # captured before tests patch httpx.Client

needs_model = pytest.mark.skipif(not (os.path.isfile(config.VISION_WEIGHTS_PATH) and NIH_PNG.is_file()),
                                 reason="checkpoint or NIH sample not present")


@pytest.fixture
def api(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(User(email="modes@example.com", hashed_password="x"))
        s.commit()

    def session_override():
        with Session(engine) as s:
            yield s

    app = FastAPI()
    app.include_router(vision_router.router)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="modes@example.com")
    monkeypatch.setattr(vision_router, "_status_cache", {"at": 0.0, "value": None})
    results.clear()
    return TestClient(app)


@pytest.fixture
def no_cloud_settings(monkeypatch):
    monkeypatch.setattr(config, "VISION_PROVIDER", "local")
    monkeypatch.setattr(config, "VISION_CLOUD_URL", "")
    monkeypatch.setattr(config, "VISION_CLOUD_TOKEN", "")


def test_local_is_the_default_provider():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("VISION_") and not k.startswith("TEXT_AI_")}
    code = ("import os; os.chdir(os.environ['TMP_DIR']); "  # no .env in cwd
            "from backend import config; from backend.services.vision import provider as p; "
            "print(config.VISION_PROVIDER, p.provider_key(), type(p.get_vision_provider()).__name__, "
            "config.TEXT_AI_PROVIDER, bool(config.VISION_CLOUD_URL), bool(config.VISION_CLOUD_TOKEN))")
    env["TMP_DIR"] = str(HERE)
    env["PYTHONPATH"] = str(ROOT)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["local", "local", "LocalVisionProvider", "ollama", "False", "False"]


@needs_model
def test_local_screening_needs_no_cloud_settings_or_network(api, no_cloud_settings, monkeypatch):
    real_connect = socket.socket.connect

    def loopback_only(sock, address):
        # the event loop uses a loopback socket pair internally; anything else is external network
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"local vision must not use the network ({host})")
        return real_connect(sock, address)

    def no_http_client(*args, **kwargs):
        raise AssertionError("local vision must not create an HTTP client")

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(cloud.httpx, "Client", no_http_client)
    resp = api.post("/api/v1/vision/screen", files={"file": ("x.png", NIH_PNG.read_bytes(), "image/png")})
    assert resp.status_code == 200
    body = resp.json()
    assert [f["pathology"] for f in body["findings"]] and len(body["findings"]) == 18
    assert sorted(f["pathology"] for f in body["findings"]) == sorted(EXPECTED_TARGETS)
    assert body["primary_finding"]["pathology"] == "Cardiomegaly"
    assert round(body["primary_finding"]["score"], 4) == 0.66
    assert body["explanation"]["target_layer"] == "features.denseblock4"


@needs_model
def test_local_status_reports_gpu_or_cpu_without_details(api, no_cloud_settings):
    from backend.services.vision import model
    model.get_vision_model()
    body = api.get("/api/v1/vision/status").json()
    assert set(body) == {"provider", "provider_configured", "model_ready", "accelerator", "status"}
    assert body["provider"] == "local" and body["provider_configured"] and body["model_ready"]
    assert body["status"] == "ready"
    assert body["accelerator"] == {"cuda": "gpu", "cpu": "cpu"}[model.loaded_device_type()]
    text = json.dumps(body)
    for leak in ("weights", ".pt", "\\\\", "/", "NVIDIA", "cuda:"):
        assert leak not in text, leak


def test_local_status_without_checkpoint(api, no_cloud_settings, monkeypatch, tmp_path):
    from backend.services.vision import model
    monkeypatch.setattr(config, "VISION_WEIGHTS_PATH", str(tmp_path / "missing.pt"))
    monkeypatch.setattr(model, "_instance", None)  # nothing loaded in this process
    info = provider.LocalVisionProvider().status()
    assert info == {"configured": False, "model_ready": False, "accelerator": None}
    body = api.get("/api/v1/vision/status").json()
    assert body["provider"] == "local" and body["status"] == "unavailable" and body["accelerator"] is None


def test_local_status_before_first_request(api, no_cloud_settings, monkeypatch):
    """Configured but not loaded yet: standby (lazy) or loading (preload), accelerator resolved."""
    from backend.services.vision import model
    if not os.path.isfile(config.VISION_WEIGHTS_PATH):
        pytest.skip("checkpoint not present")
    monkeypatch.setattr(model, "_instance", None)
    monkeypatch.setattr(config, "VISION_PRELOAD", False)
    body = api.get("/api/v1/vision/status").json()
    expected = "gpu" if model.resolve_device(config.VISION_DEVICE).type == "cuda" else "cpu"
    assert body == {"provider": "local", "provider_configured": True, "model_ready": False,
                    "accelerator": expected, "status": "standby"}


def test_cloud_must_be_explicit_and_fails_with_503(api, monkeypatch):
    """cloud selected but not configured → 503; local inference is never used."""
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    monkeypatch.setattr(config, "VISION_CLOUD_URL", "")
    monkeypatch.setattr(config, "VISION_CLOUD_TOKEN", "")
    monkeypatch.setattr(inference, "screen_image",
                        lambda *a, **k: pytest.fail("local inference used while VISION_PROVIDER=cloud"))
    resp = api.post("/api/v1/vision/screen", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Vision service is not available"}
    status = api.get("/api/v1/vision/status").json()
    assert status["provider"] == "cloud" and status["status"] == "unavailable"


def test_cloud_worker_down_is_503_without_leaks(api, monkeypatch, caplog):
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    monkeypatch.setattr(config, "VISION_CLOUD_URL", SENTINEL_URL)
    monkeypatch.setattr(config, "VISION_CLOUD_TOKEN", SENTINEL_TOKEN)
    monkeypatch.setattr(inference, "screen_image",
                        lambda *a, **k: pytest.fail("local inference used while VISION_PROVIDER=cloud"))

    def factory(*args, **kwargs):
        def refuse(request):
            raise httpx.ConnectError("connection refused by " + str(request.url))
        kwargs["transport"] = httpx.MockTransport(refuse)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr(cloud.httpx, "Client", factory)
    caplog.set_level("DEBUG")
    resp = api.post("/api/v1/vision/screen", files={"file": ("x.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
    status = api.get("/api/v1/vision/status")
    assert resp.status_code == 503
    assert status.json() == {"provider": "cloud", "provider_configured": True, "model_ready": False,
                             "accelerator": "gpu", "status": "unavailable"}
    for text in (resp.text, status.text, caplog.text):
        assert SENTINEL_TOKEN not in text
        assert "internal-worker-sentinel" not in text


def test_modal_image_ships_every_worker_dependency():
    """Regression: the Modal image must include every backend module the worker imports."""
    src = (ROOT / "deploy" / "modal" / "holomed_vision.py").read_text(encoding="utf-8")
    ns = {"Path": pathlib.Path}
    exec(src[src.index("_ALLOWED = ("):src.index("image = (")], ns)
    backend_dir = ROOT / "backend"
    shipped = {p.relative_to(backend_dir).as_posix() for p in backend_dir.rglob("*.py")
               if not ns["_ignore"](p.relative_to(backend_dir))}
    code = ("import sys, json; from backend.vision_worker.app import create_app; create_app(); "
            "from backend.services.vision import inference, model, preprocessing, explainability; "
            "print(json.dumps(sorted({getattr(m, '__file__', '') or '' for n, m in sys.modules.items() "
            "if n == 'backend' or n.startswith('backend.')})))")
    env = dict(os.environ, VISION_PRELOAD="0", PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    imported = {pathlib.Path(f).resolve().relative_to(backend_dir.resolve()).as_posix()
                for f in json.loads(out.stdout.strip().splitlines()[-1]) if f}
    missing = sorted(imported - shipped)
    assert not missing, f"backend modules imported by the worker but not shipped to Modal: {missing}"
    assert "logger.py" in shipped and "routers/vision.py" not in shipped and ".env" not in shipped
