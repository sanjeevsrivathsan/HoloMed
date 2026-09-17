import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from ..dependencies.auth import get_current_user
from ..models.user import User
from ..services import auth_cookies, google_oauth
from ..services.auth_service import (
    create_user,
    authenticate_user,
    create_access_token,
    decode_access_token,
)
from ..database import get_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(email: str, password: str, db: Session = Depends(get_session)):
    # Enforce minimum password length of 8 characters
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long")
    # Check if email already registered using SQLModel query
    stmt = select(User).where(User.email == email)
    existing = db.exec(stmt).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = create_user(email, password, db)
    return {"id": user.id, "email": user.email}

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_session)):
    user = authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token({"sub": str(user.id)})
    json_resp = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    auth_cookies.set_session_cookie(json_resp, access_token)
    return json_resp

@router.post("/logout")
def logout():
    response = JSONResponse(content={"detail": "Logged out"})
    auth_cookies.clear_session_cookie(response)
    return response

@router.post("/verify-email")
def verify_email():
    """Placeholder endpoint for future email verification flow.
    Currently returns a 501 Not Implemented response.
    """
    raise HTTPException(status_code=501, detail="Email verification not implemented")

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"id": current_user.id, "email": current_user.email,
            "google_linked": current_user.google_id is not None}


# ── Google Sign-In (OIDC authorization code + PKCE) ──────────────────────────
# Browser-facing endpoints: every outcome is a redirect, never a raw error page.

def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _clear_flow_cookie(response) -> None:
    response.delete_cookie(key=google_oauth.FLOW_COOKIE, path=google_oauth.FLOW_COOKIE_PATH,
                           httponly=True, secure=auth_cookies.secure(), samesite="lax")


def _failure(code: str) -> RedirectResponse:
    logger.warning("Google sign-in failed: %s", code)
    response = RedirectResponse(url=google_oauth.error_redirect_url(code), status_code=302)
    _clear_flow_cookie(response)
    return _no_store(response)


def _start(purpose: str, user_id: Optional[int] = None) -> RedirectResponse:
    url, flow_cookie = google_oauth.begin(purpose, user_id)
    response = RedirectResponse(url=url, status_code=302)
    # SameSite=Lax: sent on Google's top-level redirect back to the callback, not on cross-site subrequests.
    response.set_cookie(key=google_oauth.FLOW_COOKIE, value=flow_cookie, max_age=google_oauth.FLOW_TTL_SECONDS,
                        path=google_oauth.FLOW_COOKIE_PATH, httponly=True,
                        secure=auth_cookies.secure(), samesite="lax")
    return _no_store(response)


def _session_user(request: Request, db: Session) -> Optional[User]:
    """The user of a valid session cookie (no test fallbacks)."""
    token = request.cookies.get(auth_cookies.SESSION_COOKIE)
    if not token:
        return None
    try:
        user_id = int(decode_access_token(token).get("sub"))
    except Exception:
        return None
    user = db.get(User, user_id)
    return user if user is not None and user.is_active else None


@router.get("/google")
def google_login():
    """Start Google sign-in. The browser navigates here in the current tab and is redirected to
    Google; the callback returns to GOOGLE_POST_LOGIN_URL in that same tab."""
    if not google_oauth.is_configured():
        return _failure("google_not_configured")
    return _start("login")


@router.get("/google/link")
def google_link(request: Request, db: Session = Depends(get_session)):
    """Start linking Google to the currently signed-in HoloMed account (same tab)."""
    if not google_oauth.is_configured():
        return _failure("google_not_configured")
    user = _session_user(request, db)
    if user is None:
        return _failure("link_requires_login")
    return _start("link", user.id)


@router.get("/google/callback")
def google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                    error: Optional[str] = None, db: Session = Depends(get_session)):
    flow_cookie = request.cookies.get(google_oauth.FLOW_COOKIE)
    if not google_oauth.is_configured():
        return _failure("google_not_configured")
    if error:
        google_oauth.discard_flow(flow_cookie)
        return _failure("google_cancelled" if error == "access_denied" else "google_failed")
    try:
        flow = google_oauth.consume_flow(flow_cookie, state)
        if not code:
            raise google_oauth.GoogleSignInError("missing_code")
        raw_id_token = google_oauth.exchange_code(code, flow.code_verifier)
        claims = google_oauth.verify_id_token(raw_id_token, flow.nonce)
        sub, email = claims["sub"], claims["email"]

        if flow.purpose == "link":
            user = _session_user(request, db)
            if user is None or user.id != flow.user_id:
                raise google_oauth.GoogleSignInError("link_requires_login")
            google_oauth.link_google(db, user, sub, email)
            response = RedirectResponse(url=google_oauth.success_redirect_url("google_linked"),
                                        status_code=302)
            _clear_flow_cookie(response)
            return _no_store(response)

        user = google_oauth.resolve_login_user(db, sub, email)
        if not user.is_active:
            raise google_oauth.GoogleSignInError("account_disabled")
    except google_oauth.GoogleSignInError as exc:
        return _failure(exc.code)
    except Exception:
        logger.exception("Unexpected Google sign-in error")
        return _failure("google_failed")

    session_token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(url=google_oauth.success_redirect_url(), status_code=302)
    auth_cookies.set_session_cookie(response, session_token)
    _clear_flow_cookie(response)
    logger.info("Google sign-in succeeded for user %s", user.id)
    return _no_store(response)
