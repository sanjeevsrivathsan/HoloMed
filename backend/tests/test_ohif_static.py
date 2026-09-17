"""OHIF is served under /ohif with a single-page-app fallback for client-side routes."""
import re

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_ohif_index_and_assets():
    resp = client.get("/ohif/")
    assert resp.status_code == 200 and "text/html" in resp.headers["content-type"]
    assert "window.PUBLIC_URL = '/ohif/'" in resp.text
    cfg = client.get("/ohif/app-config.js")
    assert cfg.status_code == 200 and "javascript" in cfg.headers["content-type"]
    # the router basename must match the path OHIF is served from, or the viewer renders a blank page
    assert re.search(r'routerBasename:\s*"/ohif/?"', cfg.text)


def test_client_side_routes_fall_back_to_index():
    index = client.get("/ohif/").text
    for path in ("/ohif/viewer?StudyInstanceUIDs=1.2.3", "/ohif/viewer", "/ohif/local"):
        resp = client.get(path)
        assert resp.status_code == 200 and resp.text == index, path


def test_missing_assets_are_still_404():
    assert client.get("/ohif/does-not-exist.js").status_code == 404
    assert client.get("/ohif/assets/missing.png").status_code == 404
    assert client.get("/ohif/../backend/main.py").status_code == 404
