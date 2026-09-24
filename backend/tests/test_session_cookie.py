"""Session cookie + CORS for the cross-site production deployment.

Frontend: https://sanjeevsrivathsan.github.io/HoloMed/ (GitHub Pages)
API:      https://api.shadowless.app

github.io and shadowless.app are different sites, so the browser only sends the `session` cookie on
the frontend's fetch() calls when it is SameSite=None; Secure. These tests check the actual
Set-Cookie headers of real responses and the CORS headers for the GitHub Pages origin.
"""
import importlib
import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlmodel import Session, SQLModel

from backend import config
from backend.config import parse_cors_origins
from backend.database import get_session
from backend.main import app
from backend.services import auth_cookies, google_oauth
from backend.services.auth_service import create_access_token, create_user
from backend.tests.test_google_oauth import engine

PAGES_ORIGIN = "https://sanjeevsrivathsan.github.io"
PROD_CORS = f"{PAGES_ORIGIN},http://localhost:5173,http://127.0.0.1:5173"
EMAIL, PASSWORD = "cookie-user@example.com", "Password123!"


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(config, "HOLOMED_ENV", "production")
    monkeypatch.setattr(config, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(config, "SESSION_COOKIE_SAMESITE", "none")


@pytest.fixture
def development(monkeypatch):
    monkeypatch.setattr(config, "HOLOMED_ENV", "development")
    monkeypatch.setattr(config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(config, "SESSION_COOKIE_SAMESITE", "lax")


@pytest.fixture
def client(monkeypatch):
    # A real secret: "testsecret" enables the test-only unauthenticated fallback user.
    monkeypatch.setenv("JWT_SECRET", "session-cookie-test-secret")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        create_user(EMAIL, PASSWORD, s)

    def session_override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    # https base URL so the client's cookie jar returns Secure cookies, like a browser on HTTPS.
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def session_set_cookie(resp) -> str:
    return [c for c in resp.headers.get_list("set-cookie") if c.startswith("session=")][0]


def attributes(set_cookie: str) -> dict:
    parts = [p.strip() for p in set_cookie.split(";")]
    return {p.split("=", 1)[0].lower(): (p.split("=", 1)[1] if "=" in p else True) for p in parts[1:]}


def login(client):
    return client.post("/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD})


# ── production (cross-site GitHub Pages frontend) ────────────────────────────
def test_production_login_sets_cross_site_session_cookie(client, production):
    resp = login(client)
    assert resp.status_code == 200
    cookie = session_set_cookie(resp)
    token = cookie.split(";", 1)[0].split("=", 1)[1]
    assert jwt.get_unverified_claims(token)["sub"]            # session=<JWT>
    attrs = attributes(cookie)
    assert attrs.get("httponly") is True
    assert attrs.get("secure") is True
    assert attrs.get("samesite", "").lower() == "none"
    assert attrs.get("path") == "/"
    assert "domain" not in attrs                               # host-only: api.shadowless.app


def test_production_logout_clears_cookie_with_matching_attributes(client, production):
    login(client)
    assert client.get("/api/v1/auth/me").status_code == 200
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    attrs = attributes(session_set_cookie(resp))
    assert attrs.get("max-age") == "0"
    assert attrs.get("path") == "/" and attrs.get("secure") is True and attrs.get("httponly") is True
    assert attrs.get("samesite", "").lower() == "none"
    assert client.get("/api/v1/auth/me").status_code == 401


def test_production_oauth_flow_cookie_stays_lax(client, production, monkeypatch):
    """The state/nonce/PKCE flow cookie is only needed on Google's top-level redirect back to the
    callback, so it stays SameSite=Lax (and Secure) even when the session cookie is None."""
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "not-a-real-secret")
    monkeypatch.setattr(config, "GOOGLE_REDIRECT_URI", "https://api.shadowless.app/api/v1/auth/google/callback")
    resp = client.get("/api/v1/auth/google")
    assert resp.status_code == 302
    flow = [c for c in resp.headers.get_list("set-cookie") if c.startswith(google_oauth.FLOW_COOKIE + "=")][0]
    attrs = attributes(flow)
    assert attrs.get("samesite", "").lower() == "lax" and attrs.get("secure") is True
    assert attrs.get("httponly") is True and attrs.get("path") == google_oauth.FLOW_COOKIE_PATH
    assert "redirect_uri=https%3A%2F%2Fapi.shadowless.app%2Fapi%2Fv1%2Fauth%2Fgoogle%2Fcallback" \
        in resp.headers["location"]
    assert not any(c.startswith("session=") for c in resp.headers.get_list("set-cookie"))


def test_samesite_none_always_forces_secure(monkeypatch):
    monkeypatch.setattr(config, "HOLOMED_ENV", "production")
    monkeypatch.setattr(config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(config, "SESSION_COOKIE_SAMESITE", "none")
    assert auth_cookies.samesite() == "none" and auth_cookies.secure() is True


# ── local development ────────────────────────────────────────────────────────
def test_development_cookie_stays_lax_and_works_over_http(monkeypatch, development):
    monkeypatch.setenv("JWT_SECRET", "session-cookie-test-secret")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        create_user(EMAIL, PASSWORD, s)

    def session_override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app, base_url="http://testserver") as c:
            attrs = attributes(session_set_cookie(login(c)))
            assert attrs.get("samesite", "").lower() == "lax" and "secure" not in attrs
            assert attrs.get("httponly") is True and attrs.get("path") == "/"
            assert c.get("/api/v1/auth/me").status_code == 200    # sent back over plain HTTP
    finally:
        app.dependency_overrides.clear()
        SQLModel.metadata.drop_all(engine)


# ── /auth/me ─────────────────────────────────────────────────────────────────
def test_me_requires_a_session(client, production):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_returns_the_user_for_a_valid_session(client, production):
    login(client)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == EMAIL and resp.json()["google_linked"] is False


@pytest.mark.parametrize("token_factory", [
    lambda: "not-a-jwt",
    lambda: jwt.encode({"sub": "1", "exp": int(time.time()) - 60}, "session-cookie-test-secret", algorithm="HS256"),
    lambda: jwt.encode({"sub": "1", "exp": int(time.time()) + 600}, "some-other-secret", algorithm="HS256"),
    lambda: create_access_token({"sub": "999999"}),
], ids=["garbage", "expired", "wrong-signature", "unknown-user"])
def test_me_rejects_invalid_or_expired_sessions(client, production, token_factory):
    client.cookies.set("session", token_factory())
    assert client.get("/api/v1/auth/me").status_code == 401


# ── CORS for the GitHub Pages origin ─────────────────────────────────────────
def test_cors_origin_parsing():
    assert parse_cors_origins(PROD_CORS) == [PAGES_ORIGIN, "http://localhost:5173", "http://127.0.0.1:5173"]
    assert parse_cors_origins(f" {PAGES_ORIGIN}/ , http://localhost:5173 ,,") == [PAGES_ORIGIN,
                                                                                 "http://localhost:5173"]
    assert parse_cors_origins("*") == []                       # never a wildcard with credentials
    assert parse_cors_origins(f"*,{PAGES_ORIGIN}") == [PAGES_ORIGIN]


def test_production_env_values_are_read(monkeypatch):
    """backend/config.py reads the production values from the environment."""
    import backend.config as cfg
    values = {
        "HOLOMED_ENV": "production",
        "SESSION_COOKIE_SAMESITE": "none",
        "SESSION_COOKIE_SECURE": "true",
        "CORS_ORIGINS": PROD_CORS,
        "GOOGLE_REDIRECT_URI": "https://api.shadowless.app/api/v1/auth/google/callback",
        "GOOGLE_POST_LOGIN_URL": "https://sanjeevsrivathsan.github.io/HoloMed/",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    try:
        reloaded = importlib.reload(cfg)
        assert reloaded.HOLOMED_ENV == "production"
        assert reloaded.SESSION_COOKIE_SAMESITE == "none" and reloaded.SESSION_COOKIE_SECURE is True
        assert reloaded.CORS_ORIGINS == [PAGES_ORIGIN, "http://localhost:5173", "http://127.0.0.1:5173"]
        assert reloaded.GOOGLE_REDIRECT_URI == values["GOOGLE_REDIRECT_URI"]
        assert reloaded.GOOGLE_POST_LOGIN_URL == values["GOOGLE_POST_LOGIN_URL"]
    finally:
        for name in values:
            monkeypatch.delenv(name)
        importlib.reload(cfg)


def _pages_app():
    """A copy of the app's CORS middleware configured with the production origin list."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware][0]
    options = dict(cors.kwargs if hasattr(cors, "kwargs") else cors.options)
    options["allow_origins"] = parse_cors_origins(PROD_CORS)
    probe = FastAPI()
    probe.add_middleware(CORSMiddleware, **options)

    @probe.get("/api/v1/auth/me")
    def me():
        return {"ok": True}

    return probe, options


def test_cors_middleware_uses_credentials_without_wildcard():
    _, options = _pages_app()
    assert options["allow_credentials"] is True
    assert "*" not in config.CORS_ORIGINS


def test_cors_preflight_and_request_from_github_pages():
    probe, _ = _pages_app()
    with TestClient(probe) as c:
        pre = c.options("/api/v1/auth/me", headers={
            "Origin": PAGES_ORIGIN, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-holomed-patient"})
        assert pre.status_code == 200
        assert pre.headers["access-control-allow-origin"] == PAGES_ORIGIN
        assert pre.headers["access-control-allow-credentials"] == "true"
        got = c.get("/api/v1/auth/me", headers={"Origin": PAGES_ORIGIN, "Cookie": "session=x"})
        assert got.headers["access-control-allow-origin"] == PAGES_ORIGIN
        assert got.headers["access-control-allow-credentials"] == "true"
        other = c.get("/api/v1/auth/me", headers={"Origin": "https://evil.example", "Cookie": "session=x"})
        assert "access-control-allow-origin" not in other.headers
        bad_pre = c.options("/api/v1/auth/me", headers={
            "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert bad_pre.status_code == 400
