"""Google Sign-In: OpenID Connect authorization-code flow with PKCE.

Flow:
  1. ``begin()`` creates a random ``state``, a PKCE ``code_verifier`` (S256
     challenge sent to Google) and an OIDC ``nonce``. They are kept only in a
     short-lived, HttpOnly, signed cookie (``holomed_google_oauth``); the browser
     JavaScript never sees them.
  2. ``consume_flow()`` validates that cookie on the callback: signature, expiry,
     single use, and a constant-time ``state`` comparison.
  3. ``exchange_code()`` redeems the authorization code with the client secret
     and the PKCE verifier. Only the ID token is used; access tokens are never
     stored.
  4. ``verify_id_token()`` verifies the ID token with Google's library
     (signature, issuer, audience, iat, exp), then checks nbf, nonce, sub,
     email and email_verified.
  5. ``resolve_login_user()`` / ``link_google()`` map Google's stable ``sub`` to a
     HoloMed user without silently attaching Google to password accounts.

Nothing sensitive (codes, tokens, state, verifier, client secret) is logged or
placed in redirect URLs; failures carry only a short error code.
"""
import base64
import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jose import JWTError, jwt
from sqlalchemy import func
from sqlmodel import Session, select

from .. import config
from ..models.user import User
from .auth_service import _get_jwt_secret

logger = logging.getLogger(__name__)

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"
FLOW_COOKIE = "holomed_google_oauth"
FLOW_COOKIE_PATH = "/api/v1/auth/google"
FLOW_TTL_SECONDS = 600
CLOCK_SKEW_SECONDS = 30
HTTP_TIMEOUT_SECONDS = 10.0
_FLOW_TYPE = "google_oauth_flow"


class GoogleSignInError(Exception):
    """A Google sign-in failure identified by a safe, user-facing error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Flow:
    state: str
    code_verifier: str
    nonce: str
    purpose: str            # "login" | "link"
    user_id: Optional[int]  # set for "link"


# ── configuration & URLs ─────────────────────────────────────────────────────
def is_configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and config.GOOGLE_REDIRECT_URI)


def _with_query(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in params]
    query.extend(params.items())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def error_redirect_url(code: str) -> str:
    return _with_query(config.GOOGLE_POST_LOGIN_URL, auth_error=code)


def success_redirect_url(notice: Optional[str] = None) -> str:
    """Where the callback sends the browser. Plain URL on success, so no auth parameters stay in
    the address bar; a short, non-sensitive code on failure."""
    return _with_query(config.GOOGLE_POST_LOGIN_URL, auth_notice=notice) if notice \
        else config.GOOGLE_POST_LOGIN_URL


# ── access-log redaction ─────────────────────────────────────────────────────
CALLBACK_PATH = "/api/v1/auth/google/callback"


class RedactOAuthCallbackQuery(logging.Filter):
    """Strip the query string (code, state) from access-log lines for the callback."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = args[2]
            if path.startswith(CALLBACK_PATH + "?"):
                record.args = args[:2] + (CALLBACK_PATH + "?[redacted]",) + args[3:]
        return True


def install_access_log_redaction(logger_name: str = "uvicorn.access") -> None:
    target = logging.getLogger(logger_name)
    if not any(isinstance(f, RedactOAuthCallbackQuery) for f in target.filters):
        target.addFilter(RedactOAuthCallbackQuery())


# ── state / PKCE / nonce ─────────────────────────────────────────────────────
def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def begin(purpose: str = "login", user_id: Optional[int] = None) -> tuple:
    """Return (authorization_url, signed_flow_cookie_value)."""
    if purpose not in ("login", "link"):
        raise ValueError("invalid purpose")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636's 43–128
    nonce = secrets.token_urlsafe(32)
    now = int(time.time())
    cookie = jwt.encode({
        "typ": _FLOW_TYPE, "jti": secrets.token_urlsafe(16), "iat": now, "exp": now + FLOW_TTL_SECONDS,
        "st": state, "cv": verifier, "nn": nonce, "pur": purpose, "uid": user_id,
    }, _get_jwt_secret(), algorithm="HS256")
    url = AUTHORIZATION_ENDPOINT + "?" + urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    })
    return url, cookie


_used_lock = threading.Lock()
_used_flow_ids: dict = {}  # jti -> expiry (epoch seconds); enforces single use per process
_MAX_USED = 10_000


def _mark_used(jti: str, exp: int) -> bool:
    """Record a flow id; False if it was already used."""
    now = time.time()
    with _used_lock:
        for key in [k for k, e in _used_flow_ids.items() if e < now]:
            del _used_flow_ids[key]
        if jti in _used_flow_ids:
            return False
        if len(_used_flow_ids) >= _MAX_USED:
            _used_flow_ids.pop(next(iter(_used_flow_ids)))
        _used_flow_ids[jti] = exp
        return True


def consume_flow(cookie_value: Optional[str], state: Optional[str]) -> Flow:
    """Validate and consume the flow cookie; raises GoogleSignInError('invalid_state')."""
    if not cookie_value or not state:
        raise GoogleSignInError("invalid_state")
    try:
        data = jwt.decode(cookie_value, _get_jwt_secret(), algorithms=["HS256"])
    except JWTError:
        raise GoogleSignInError("invalid_state") from None
    if data.get("typ") != _FLOW_TYPE or not isinstance(data.get("jti"), str):
        raise GoogleSignInError("invalid_state")
    if not _mark_used(data["jti"], int(data.get("exp", 0))):
        raise GoogleSignInError("invalid_state")
    expected = data.get("st")
    if not isinstance(expected, str) or not hmac.compare_digest(expected.encode(), state.encode()):
        raise GoogleSignInError("invalid_state")
    purpose = data.get("pur")
    uid = data.get("uid")
    if purpose not in ("login", "link") or (purpose == "link" and not isinstance(uid, int)):
        raise GoogleSignInError("invalid_state")
    return Flow(state=expected, code_verifier=data.get("cv", ""), nonce=data.get("nn", ""),
                purpose=purpose, user_id=uid)


def discard_flow(cookie_value: Optional[str]) -> None:
    """Best-effort: mark a flow as used (e.g. when the user cancelled)."""
    if not cookie_value:
        return
    try:
        data = jwt.decode(cookie_value, _get_jwt_secret(), algorithms=["HS256"])
        if data.get("typ") == _FLOW_TYPE and isinstance(data.get("jti"), str):
            _mark_used(data["jti"], int(data.get("exp", 0)))
    except JWTError:
        pass


# ── token exchange & ID token verification ───────────────────────────────────
def exchange_code(code: str, code_verifier: str) -> str:
    """Redeem the authorization code; returns the raw ID token (nothing is stored)."""
    if not code_verifier:
        raise GoogleSignInError("invalid_state")
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False) as client:
            resp = client.post(TOKEN_ENDPOINT, data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            }, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        logger.warning("Google token exchange failed: %s", type(exc).__name__)
        raise GoogleSignInError("token_exchange_failed") from None
    if resp.status_code != 200:
        # Google's error body may echo request details; log only the status.
        logger.warning("Google token exchange rejected: HTTP %s", resp.status_code)
        raise GoogleSignInError("token_exchange_failed")
    try:
        raw = resp.json().get("id_token")
    except (ValueError, AttributeError):
        raw = None
    if not isinstance(raw, str) or not raw:
        raise GoogleSignInError("invalid_id_token")
    return raw


def _google_request():
    """Transport used to fetch Google's signing certificates (patched in tests)."""
    return google_requests.Request()


def verify_id_token(raw: str, nonce: str) -> dict:
    try:
        claims = google_id_token.verify_oauth2_token(
            raw, _google_request(), audience=config.GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=CLOCK_SKEW_SECONDS)
    except google_exceptions.TransportError:
        logger.warning("Could not fetch Google signing certificates")
        raise GoogleSignInError("google_failed") from None
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        code = "id_token_expired" if "expired" in str(exc).lower() else "invalid_id_token"
        logger.warning("Google ID token rejected (%s)", code)
        raise GoogleSignInError(code) from None
    now = time.time()
    nbf = claims.get("nbf")
    if nbf is not None and (not isinstance(nbf, (int, float)) or now + CLOCK_SKEW_SECONDS < nbf):
        raise GoogleSignInError("invalid_id_token")
    token_nonce = claims.get("nonce")
    if not nonce or not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce.encode(), nonce.encode()):
        raise GoogleSignInError("invalid_id_token")
    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str) or not sub or not isinstance(email, str) or "@" not in email:
        raise GoogleSignInError("invalid_id_token")
    verified = claims.get("email_verified")
    if not (verified is True or (isinstance(verified, str) and verified.lower() == "true")):
        raise GoogleSignInError("email_unverified")
    return claims


# ── account mapping ──────────────────────────────────────────────────────────
def _user_by_google_sub(db: Session, sub: str) -> Optional[User]:
    return db.exec(select(User).where(User.google_id == sub)).first()


def _user_by_email(db: Session, email: str) -> Optional[User]:
    return db.exec(select(User).where(func.lower(User.email) == email.lower())).first()


def resolve_login_user(db: Session, sub: str, email: str) -> User:
    """Map a verified Google identity to a HoloMed user for sign-in.

    A. google_id == sub                          → that user
    B. no user with this email                   → new Google-only user
    C. email exists, not Google-linked           → refuse (explicit linking required)
    D. email exists, linked to this same sub     → covered by A
       email exists, linked to a different sub   → refuse
    """
    user = _user_by_google_sub(db, sub)
    if user is not None:
        return user
    existing = _user_by_email(db, email)
    if existing is not None:
        if existing.google_id is None:
            raise GoogleSignInError("account_link_required")
        raise GoogleSignInError("google_account_mismatch")
    user = User(email=email.lower(), google_id=sub, hashed_password=None, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def link_google(db: Session, user: User, sub: str, email: str) -> User:
    """Explicitly attach a verified Google identity to an authenticated user."""
    other = _user_by_google_sub(db, sub)
    if other is not None and other.id != user.id:
        raise GoogleSignInError("google_account_in_use")      # E
    if user.google_id is not None and user.google_id != sub:
        raise GoogleSignInError("google_account_mismatch")
    if user.email.lower() != email.lower():
        raise GoogleSignInError("email_mismatch")
    if user.google_id != sub:
        user.google_id = sub
        db.add(user)
        db.commit()
        db.refresh(user)
    return user
