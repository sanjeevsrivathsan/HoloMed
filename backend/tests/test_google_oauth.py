"""Google Sign-In hardening: state, PKCE, OIDC ID-token verification, account linking.

No network: Google's token endpoint is an httpx MockTransport and Google's
certificate endpoint is a fake transport. ID tokens are signed with a test RSA
key and verified by Google's real library (google.oauth2.id_token).
"""
import datetime
import json
import logging
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt as google_crypt
from google.auth import exceptions as google_exceptions
from google.auth import jwt as google_jwt
from jose import jwt as jose_jwt
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import config
from backend.database import get_session
from backend.main import app
from backend.models.user import User
from backend.services import google_oauth
from backend.services.auth_service import create_user

_REAL_HTTPX_CLIENT = httpx.Client  # captured before tests patch httpx.Client

CLIENT_ID = "1234567890-testclient.apps.googleusercontent.com"
CLIENT_SECRET = "GOOGLE-CLIENT-SECRET-SENTINEL-7731"
POST_LOGIN = "http://localhost:5173/"
REDIRECT_URI = "http://localhost:5173/api/v1/auth/google/callback"
AUTH_CODE = "4/AUTH-CODE-SENTINEL-5521"
ACCESS_TOKEN = "ya29.ACCESS-TOKEN-SENTINEL-9043"
SUB = "109876543210987654321"
EMAIL = "alice@example.com"
KID = "holomed-test-kid"
JWT_SECRET = "google-oauth-test-jwt-secret-please-change"

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _make_key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "holomed-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.NoEncryption()).decode()
    return pem_key, cert.public_bytes(serialization.Encoding.PEM).decode()


PRIVATE_PEM, CERT_PEM = _make_key_and_cert()
OTHER_PRIVATE_PEM, _ = _make_key_and_cert()


class _CertResponse:
    status = 200

    def __init__(self, payload):
        self.data = json.dumps(payload).encode()
        self.headers = {}


class FakeCertTransport:
    def __init__(self, fail=False):
        self.fail = fail

    def __call__(self, url, method="GET", **kwargs):
        if self.fail:
            raise google_exceptions.TransportError("unreachable")
        assert url == "https://www.googleapis.com/oauth2/v1/certs"
        return _CertResponse({KID: CERT_PEM})


def make_id_token(expected_nonce, *, key=PRIVATE_PEM, **overrides):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": SUB, "email": EMAIL,
              "email_verified": True, "iat": now, "exp": now + 600, "nonce": expected_nonce}
    for k, v in overrides.items():
        if v is None:
            claims.pop(k, None)
        else:
            claims[k] = v
    signer = google_crypt.RSASigner.from_string(key, key_id=KID)
    return google_jwt.encode(signer, claims).decode()


class GoogleMock:
    """Stateful fake of Google's token endpoint (validates PKCE like Google does)."""

    def __init__(self):
        self.challenge = None
        self.nonce = None
        self.requests = []
        self.id_token_overrides = {}
        self.id_token_key = PRIVATE_PEM
        self.raw_id_token = None
        self.status = 200
        self.network_error = False
        self.omit_id_token = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        form = parse_qs(request.content.decode())
        self.requests.append({k: v[0] for k, v in form.items()})
        if self.network_error:
            raise httpx.ConnectError("unreachable")
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "server_error", "echo": AUTH_CODE})
        verifier = form.get("code_verifier", [""])[0]
        if google_oauth.pkce_challenge(verifier) != self.challenge:
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "code_verifier"})
        body = {"access_token": ACCESS_TOKEN, "expires_in": 3599, "token_type": "Bearer",
                "scope": "openid email profile"}
        if not self.omit_id_token:
            body["id_token"] = self.raw_id_token or make_id_token(self.nonce, key=self.id_token_key,
                                                                  **self.id_token_overrides)
        return httpx.Response(200, json=body)


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setattr(config, "GOOGLE_REDIRECT_URI", REDIRECT_URI)
    monkeypatch.setattr(config, "GOOGLE_POST_LOGIN_URL", POST_LOGIN)
    monkeypatch.setattr(config, "HOLOMED_ENV", "development")
    monkeypatch.setattr(config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(config, "SESSION_COOKIE_SAMESITE", "lax")
    mock = GoogleMock()
    cert_transport = FakeCertTransport()
    monkeypatch.setattr(google_oauth, "_google_request", lambda: cert_transport)

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock.handler)
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr(google_oauth.httpx, "Client", client_factory)
    mock.cert_transport = cert_transport
    return mock


@pytest.fixture
def client(google):
    SQLModel.metadata.create_all(engine)

    def session_override():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def users():
    with Session(engine) as s:
        return s.exec(select(User)).all()


def start(client, google, path="/api/v1/auth/google"):
    resp = client.get(path)
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    params = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    if location.startswith(google_oauth.AUTHORIZATION_ENDPOINT):
        google.challenge = params["code_challenge"]
        google.nonce = params["nonce"]
    return resp, params


def callback(client, **params):
    return client.get("/api/v1/auth/google/callback", params=params)


def auth_error(resp):
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(POST_LOGIN)
    return parse_qs(urlsplit(location).query).get("auth_error", [None])[0]


def set_cookies(resp):
    return resp.headers.get_list("set-cookie")


def session_cookie_set(resp):
    return any(c.startswith("session=") and "Max-Age=0" not in c and 'session=""' not in c
               for c in set_cookies(resp))


def flow_cookie_cleared(resp):
    return any(c.startswith(google_oauth.FLOW_COOKIE + "=") and ("Max-Age=0" in c or "expires=" in c.lower())
               for c in set_cookies(resp))


def plant_flow_cookie(client, value):
    """Replace the jar with a single flow cookie (as a browser would hold it)."""
    client.cookies.set(google_oauth.FLOW_COOKIE, value, domain="testserver.local",
                       path=google_oauth.FLOW_COOKIE_PATH)


def forge_flow_cookie(secret=JWT_SECRET, **overrides):
    now = int(time.time())
    data = {"typ": "google_oauth_flow", "jti": f"forged-{now}-{id(overrides)}", "iat": now, "exp": now + 600,
            "st": "forged-state", "cv": "v" * 64, "nn": "forged-nonce", "pur": "login", "uid": None}
    data.update(overrides)
    return jose_jwt.encode(data, secret, algorithm="HS256")


# ── authorization request ─────────────────────────────────────────────────
def test_authorization_redirect(client, google):
    resp, p = start(client, google)
    assert resp.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert p["client_id"] == CLIENT_ID and p["redirect_uri"] == REDIRECT_URI
    assert p["response_type"] == "code"
    assert p["scope"].split() == ["openid", "email", "profile"]
    assert p["access_type"] == "online" and "offline" not in resp.headers["location"]
    assert p["code_challenge_method"] == "S256"
    assert len(p["code_challenge"]) == 43 and "=" not in p["code_challenge"]
    assert len(p["state"]) >= 43 and len(p["nonce"]) >= 43
    assert CLIENT_SECRET not in resp.headers["location"]
    assert resp.headers["cache-control"] == "no-store"
    flow = [c for c in set_cookies(resp) if c.startswith(google_oauth.FLOW_COOKIE + "=")]
    assert len(flow) == 1
    attrs = flow[0].lower()
    assert "httponly" in attrs and "samesite=lax" in attrs and "max-age=600" in attrs
    assert "path=/api/v1/auth/google" in attrs and "secure" not in attrs  # local HTTP development
    assert p["state"] not in flow[0]  # the cookie is a signed token, not the raw state


def test_each_attempt_is_unique(client, google):
    _, a = start(client, google)
    _, b = start(client, google)
    assert a["state"] != b["state"] and a["code_challenge"] != b["code_challenge"] and a["nonce"] != b["nonce"]


def test_pkce_challenge_is_s256_of_verifier():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert google_oauth.pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_not_configured_redirects_cleanly(client, google, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "")
    resp = client.get("/api/v1/auth/google")
    assert auth_error(resp) == "google_not_configured"
    assert auth_error(callback(client, code="x", state="y")) == "google_not_configured"
    assert google.requests == []


# ── successful sign-in ────────────────────────────────────────────────────
def test_valid_google_login_creates_google_only_account(client, google, caplog):
    caplog.set_level(logging.DEBUG)
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert resp.status_code == 302 and resp.headers["location"] == POST_LOGIN
    assert session_cookie_set(resp) and flow_cookie_cleared(resp)
    [user] = users()
    assert user.google_id == SUB and user.google_id != user.email
    assert user.email == EMAIL and user.hashed_password is None
    token_request = google.requests[0]
    assert token_request["code"] == AUTH_CODE and token_request["client_secret"] == CLIENT_SECRET
    assert token_request["redirect_uri"] == REDIRECT_URI and token_request["grant_type"] == "authorization_code"
    assert google_oauth.pkce_challenge(token_request["code_verifier"]) == p["code_challenge"]
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json() == {"id": user.id, "email": EMAIL, "google_linked": True}
    session = client.cookies.get("session")
    payload = jose_jwt.decode(session, JWT_SECRET, algorithms=["HS256"])
    assert payload["sub"] == str(user.id) and set(payload) == {"sub", "exp"}  # same session format
    server_logs = chr(10).join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    for secret in (CLIENT_SECRET, AUTH_CODE, ACCESS_TOKEN, p["state"], token_request["code_verifier"]):
        assert secret not in resp.headers["location"]
        assert secret not in server_logs  # (httpx records are the test client's own request log)
    assert "id_token" not in resp.text and ACCESS_TOKEN not in resp.text


def test_existing_google_linked_account_signs_in(client, google):
    with Session(engine) as s:
        s.add(User(email=EMAIL, google_id=SUB, hashed_password=None))
        s.commit()
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert resp.headers["location"] == POST_LOGIN and session_cookie_set(resp)
    assert len(users()) == 1


def test_google_linked_password_account_signs_in_and_keeps_password(client, google):
    with Session(engine) as s:
        user = create_user(EMAIL, "Password123!", s)
        user.google_id = SUB
        s.add(user)
        s.commit()
    _, p = start(client, google)
    assert callback(client, code=AUTH_CODE, state=p["state"]).headers["location"] == POST_LOGIN
    assert client.post("/api/v1/auth/login", data={"username": EMAIL, "password": "Password123!"}).status_code == 200


# ── state / CSRF ──────────────────────────────────────────────────────────
def test_missing_state_parameter(client, google):
    start(client, google)
    resp = callback(client, code=AUTH_CODE)
    assert auth_error(resp) == "invalid_state" and flow_cookie_cleared(resp)
    assert google.requests == [] and users() == [] and not session_cookie_set(resp)


def test_missing_state_cookie(client, google):
    _, p = start(client, google)
    client.cookies.clear()
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "invalid_state" and google.requests == [] and users() == []


def test_mismatched_state(client, google):
    start(client, google)
    resp = callback(client, code=AUTH_CODE, state="attacker-state")
    assert auth_error(resp) == "invalid_state" and google.requests == [] and users() == []


def test_expired_state(client, google, monkeypatch):
    monkeypatch.setattr(google_oauth, "FLOW_TTL_SECONDS", -5)
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "invalid_state" and google.requests == [] and users() == []


def test_forged_flow_cookie_rejected(client, google):
    plant_flow_cookie(client, forge_flow_cookie(secret="not-the-server-secret"))
    resp = callback(client, code=AUTH_CODE, state="forged-state")
    assert auth_error(resp) == "invalid_state" and google.requests == []


def test_state_reuse_rejected(client, google):
    _, p = start(client, google)
    flow_cookie = client.cookies.get(google_oauth.FLOW_COOKIE)
    assert callback(client, code=AUTH_CODE, state=p["state"]).headers["location"] == POST_LOGIN
    plant_flow_cookie(client, flow_cookie)
    replay = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(replay) == "invalid_state" and not session_cookie_set(replay)
    assert len(google.requests) == 1


# ── PKCE ──────────────────────────────────────────────────────────────────
def test_missing_code_verifier(client, google):
    plant_flow_cookie(client, forge_flow_cookie(cv=""))
    resp = callback(client, code=AUTH_CODE, state="forged-state")
    assert auth_error(resp) == "invalid_state" and google.requests == [] and users() == []


def test_invalid_code_verifier_rejected_by_token_endpoint(client, google):
    _, p = start(client, google)
    stolen = forge_flow_cookie(st=p["state"], cv="w" * 64, nn=p["nonce"])
    plant_flow_cookie(client, stolen)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "token_exchange_failed" and users() == [] and not session_cookie_set(resp)
    assert google.requests[0]["code_verifier"] == "w" * 64


# ── ID token verification ─────────────────────────────────────────────────
@pytest.mark.parametrize("overrides,expected", [
    ({"aud": "someone-else.apps.googleusercontent.com"}, "invalid_id_token"),
    ({"iss": "https://evil.example.com"}, "invalid_id_token"),
    ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, "id_token_expired"),
    ({"iat": int(time.time()) + 3600, "exp": int(time.time()) + 7200}, "invalid_id_token"),
    ({"nbf": int(time.time()) + 3600}, "invalid_id_token"),
    ({"nonce": "replayed-nonce"}, "invalid_id_token"),
    ({"nonce": None}, "invalid_id_token"),
    ({"sub": None}, "invalid_id_token"),
    ({"email": None}, "invalid_id_token"),
    ({"email_verified": False}, "email_unverified"),
    ({"email_verified": "false"}, "email_unverified"),
    ({"email_verified": None}, "email_unverified"),
])
def test_id_token_claims_rejected(client, google, overrides, expected):
    google.id_token_overrides = overrides
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == expected
    assert users() == [] and not session_cookie_set(resp) and flow_cookie_cleared(resp)


def test_accepts_bare_issuer_and_string_email_verified(client, google):
    google.id_token_overrides = {"iss": "accounts.google.com", "email_verified": "true"}
    _, p = start(client, google)
    assert callback(client, code=AUTH_CODE, state=p["state"]).headers["location"] == POST_LOGIN


def test_bad_signature_rejected(client, google):
    google.id_token_key = OTHER_PRIVATE_PEM
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "invalid_id_token"
    assert users() == []


def test_malformed_and_missing_id_token(client, google):
    google.raw_id_token = "not-a-jwt"
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "invalid_id_token"
    google.raw_id_token = None
    google.omit_id_token = True
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "invalid_id_token"
    assert users() == []


def test_certificate_fetch_failure(client, google):
    google.cert_transport.fail = True
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "google_failed"
    assert users() == []


# ── Google errors ─────────────────────────────────────────────────────────
def test_user_cancellation(client, google):
    _, p = start(client, google)
    flow_cookie = client.cookies.get(google_oauth.FLOW_COOKIE)
    resp = callback(client, error="access_denied", state=p["state"])
    assert auth_error(resp) == "google_cancelled" and flow_cookie_cleared(resp)
    assert google.requests == [] and users() == []
    # the cancelled flow cannot be reused
    plant_flow_cookie(client, flow_cookie)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "invalid_state"


def test_other_google_error(client, google):
    _, p = start(client, google)
    assert auth_error(callback(client, error="server_error", state=p["state"])) == "google_failed"


def test_missing_authorization_code(client, google):
    _, p = start(client, google)
    assert auth_error(callback(client, state=p["state"])) == "missing_code"
    assert google.requests == []


@pytest.mark.parametrize("status,network", [(500, False), (401, False), (200, True)])
def test_token_exchange_failure(client, google, caplog, status, network):
    caplog.set_level(logging.DEBUG)
    google.status, google.network_error = status, network
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "token_exchange_failed" and users() == []
    assert AUTH_CODE not in caplog.text and CLIENT_SECRET not in caplog.text


# ── account linking ───────────────────────────────────────────────────────
def test_password_account_with_same_email_is_not_silently_linked(client, google):
    with Session(engine) as s:
        create_user(EMAIL, "AttackerChosen123!", s)
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "account_link_required" and not session_cookie_set(resp)
    [user] = users()
    assert user.google_id is None
    assert client.post("/api/v1/auth/login", data={"username": EMAIL, "password": "AttackerChosen123!"}).status_code == 200


def test_email_match_is_case_insensitive(client, google):
    with Session(engine) as s:
        create_user(EMAIL.upper(), "Password123!", s)
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "account_link_required"
    assert len(users()) == 1


def test_email_linked_to_different_google_identity(client, google):
    with Session(engine) as s:
        s.add(User(email=EMAIL, google_id="another-google-sub", hashed_password=None))
        s.commit()
    _, p = start(client, google)
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "google_account_mismatch"
    assert [u.google_id for u in users()] == ["another-google-sub"]


def login_password(client, email, password):
    assert client.post("/api/v1/auth/login", data={"username": email, "password": password}).status_code == 200


def test_explicit_linking_from_authenticated_account(client, google):
    with Session(engine) as s:
        create_user(EMAIL, "Password123!", s)
    login_password(client, EMAIL, "Password123!")
    _, p = start(client, google, "/api/v1/auth/google/link")
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert resp.headers["location"] == POST_LOGIN + "?auth_notice=google_linked"
    assert not session_cookie_set(resp)  # the existing session is kept
    [user] = users()
    assert user.google_id == SUB and user.hashed_password
    # now Google sign-in reaches the same account, and the password still works
    client.cookies.clear()
    _, p = start(client, google)
    assert callback(client, code=AUTH_CODE, state=p["state"]).headers["location"] == POST_LOGIN
    assert client.get("/api/v1/auth/me").json()["id"] == user.id
    login_password(client, EMAIL, "Password123!")


def test_link_requires_session(client, google):
    resp = client.get("/api/v1/auth/google/link")
    assert auth_error(resp) == "link_requires_login"


def test_link_requires_same_session_at_callback(client, google):
    with Session(engine) as s:
        create_user(EMAIL, "Password123!", s)
    login_password(client, EMAIL, "Password123!")
    _, p = start(client, google, "/api/v1/auth/google/link")
    assert client.post("/api/v1/auth/logout").status_code == 200
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "link_requires_login"
    assert users()[0].google_id is None


def test_link_rejects_google_identity_of_another_account(client, google):
    with Session(engine) as s:
        s.add(User(email="owner@example.com", google_id=SUB, hashed_password=None))
        create_user(EMAIL, "Password123!", s)
        s.commit()
    login_password(client, EMAIL, "Password123!")
    _, p = start(client, google, "/api/v1/auth/google/link")
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "google_account_in_use"
    by_email = {u.email: u.google_id for u in users()}
    assert by_email == {"owner@example.com": SUB, EMAIL: None}


def test_link_requires_matching_email(client, google):
    with Session(engine) as s:
        create_user("bob@example.com", "Password123!", s)
    login_password(client, "bob@example.com", "Password123!")
    _, p = start(client, google, "/api/v1/auth/google/link")
    assert auth_error(callback(client, code=AUTH_CODE, state=p["state"])) == "email_mismatch"
    assert users()[0].google_id is None


def test_disabled_account_cannot_sign_in(client, google):
    with Session(engine) as s:
        s.add(User(email=EMAIL, google_id=SUB, hashed_password=None, is_active=False))
        s.commit()
    _, p = start(client, google)
    resp = callback(client, code=AUTH_CODE, state=p["state"])
    assert auth_error(resp) == "account_disabled" and not session_cookie_set(resp)


def test_error_redirect_keeps_existing_query(client, google, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_POST_LOGIN_URL", "https://app.example.org/login?lang=en")
    resp = client.get("/api/v1/auth/google/callback", params={"error": "access_denied"})
    assert resp.headers["location"] == "https://app.example.org/login?lang=en&auth_error=google_cancelled"


# ── session & password auth unchanged ─────────────────────────────────────
def test_password_registration_login_me_logout(client, google):
    assert client.post("/api/v1/auth/register", params={"email": "carol@example.com",
                                                        "password": "Password123!"}).status_code == 201
    resp = client.post("/api/v1/auth/login", data={"username": "carol@example.com", "password": "Password123!"})
    assert resp.status_code == 200 and set(resp.json()) == {"access_token", "token_type"}
    cookie = [c for c in set_cookies(resp) if c.startswith("session=")][0].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "secure" not in cookie
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["google_linked"] is False
    out = client.post("/api/v1/auth/logout")
    assert out.status_code == 200 and out.json() == {"detail": "Logged out"}
    assert any(c.startswith("session=") and "max-age=0" in c.lower() for c in set_cookies(out))
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/login", data={"username": "carol@example.com",
                                                   "password": "wrong-password"}).status_code == 401


def test_google_only_account_cannot_use_password_login(client, google):
    _, p = start(client, google)
    callback(client, code=AUTH_CODE, state=p["state"])
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", data={"username": EMAIL, "password": "anything123"}).status_code == 401


@pytest.mark.parametrize("env,secure_setting,samesite,expect_secure,expect_samesite", [
    ("production", True, "lax", True, "lax"),
    ("development", False, "lax", False, "lax"),
    ("development", False, "none", True, "none"),
    ("production", True, "strict", True, "strict"),
    ("development", False, "bogus", False, "lax"),
])
def test_cookie_configuration(client, google, monkeypatch, env, secure_setting, samesite,
                              expect_secure, expect_samesite):
    monkeypatch.setattr(config, "HOLOMED_ENV", env)
    monkeypatch.setattr(config, "SESSION_COOKIE_SECURE", secure_setting)
    monkeypatch.setattr(config, "SESSION_COOKIE_SAMESITE", samesite)
    with Session(engine) as s:
        create_user("dave@example.com", "Password123!", s)
    resp = client.post("/api/v1/auth/login", data={"username": "dave@example.com", "password": "Password123!"})
    cookie = [c for c in set_cookies(resp) if c.startswith("session=")][0].lower()
    assert ("secure" in cookie) is expect_secure
    assert f"samesite={expect_samesite}" in cookie and "httponly" in cookie
    flow = [c for c in set_cookies(client.get("/api/v1/auth/google")) if c.startswith(google_oauth.FLOW_COOKIE)][0]
    assert ("secure" in flow.lower()) is expect_secure and "samesite=lax" in flow.lower()


def test_production_secure_default(monkeypatch):
    import importlib
    import backend.config as cfg
    monkeypatch.setenv("HOLOMED_ENV", "production")
    for name in ("SESSION_COOKIE_SECURE", "SESSION_COOKIE_SAMESITE", "GOOGLE_REDIRECT_URI", "GOOGLE_POST_LOGIN_URL"):
        monkeypatch.delenv(name, raising=False)
    try:
        reloaded = importlib.reload(cfg)
        assert reloaded.SESSION_COOKIE_SECURE is True and reloaded.SESSION_COOKIE_SAMESITE == "lax"
        assert reloaded.GOOGLE_REDIRECT_URI == REDIRECT_URI and reloaded.GOOGLE_POST_LOGIN_URL == POST_LOGIN
    finally:
        monkeypatch.delenv("HOLOMED_ENV")
        importlib.reload(cfg)


def test_no_oauth_credentials_in_configuration_defaults():
    import inspect
    import backend.config as cfg
    source = inspect.getsource(cfg)
    assert "apps.googleusercontent.com" not in source and "GOCSPX" not in source


def test_access_log_redacts_callback_query():
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", f"/api/v1/auth/google/callback?code={AUTH_CODE}&state=abc",
                                "1.1", 302), None)
    assert google_oauth.RedactOAuthCallbackQuery().filter(record)
    assert AUTH_CODE not in record.getMessage() and "abc" not in record.getMessage()
    assert "/api/v1/auth/google/callback?[redacted]" in record.getMessage()
    other = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                              ("127.0.0.1:5000", "GET", "/api/v1/vision/status?x=1", "1.1", 200), None)
    google_oauth.RedactOAuthCallbackQuery().filter(other)
    assert "/api/v1/vision/status?x=1" in other.getMessage()
    google_oauth.install_access_log_redaction()
    assert any(isinstance(f, google_oauth.RedactOAuthCallbackQuery)
               for f in logging.getLogger("uvicorn.access").filters)
