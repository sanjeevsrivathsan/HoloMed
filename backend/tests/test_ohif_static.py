"""OHIF is served under /ohif with a single-page-app fallback for client-side routes.

index.html names app-config.js by content version and is never stored, so a browser cannot keep
running OHIF with an outdated data-source configuration (an old cached app-config.js without the
`holomed` source left the viewer black without requesting any data)."""
import hashlib
import os
import re

from fastapi.testclient import TestClient

from backend.main import OHIF_DIR, app

client = TestClient(app)


def _version() -> str:
    with open(os.path.join(OHIF_DIR, "app-config.js"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


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
    for path in ("/ohif/viewer?StudyInstanceUIDs=1.2.3", "/ohif/viewer", "/ohif/local",
                 "/ohif/viewer/holomed?url=%2Fx&studyInstanceUIDs=1.2.3"):
        resp = client.get(path)
        assert resp.status_code == 200 and resp.text == index, path


def test_missing_assets_are_still_404():
    assert client.get("/ohif/does-not-exist.js").status_code == 404
    assert client.get("/ohif/assets/missing.png").status_code == 404
    assert client.get("/ohif/../backend/main.py").status_code == 404


def test_index_references_versioned_app_config_and_is_not_stored():
    for path in ("/ohif/", "/ohif/index.html", "/ohif/viewer/holomed?url=%2Fx&studyInstanceUIDs=1.2.3"):
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.headers["cache-control"] == "no-store", path
        assert f'src="/ohif/app-config.js?v={_version()}"' in resp.text, path
        assert 'src="/ohif/app-config.js"' not in resp.text, path


def test_versioned_app_config_names_the_patient_scoped_source():
    resp = client.get(f"/ohif/app-config.js?v={_version()}")
    assert resp.status_code == 200 and "javascript" in resp.headers["content-type"]
    assert resp.headers["cache-control"] == "no-cache"
    assert 'sourceName:"holomed"' in resp.text and "dataSourcesModule.dicomwebproxy" in resp.text
