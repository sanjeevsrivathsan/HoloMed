"""Session cookie settings shared by password and Google sign-in.

The session itself is unchanged: an HS256 JWT (``sub`` = user id) in the
HttpOnly cookie ``session``. Only its transport attributes are configurable:

- ``SESSION_COOKIE_SECURE``: defaults to true when HOLOMED_ENV=production.
- ``SESSION_COOKIE_SAMESITE``: lax (default), strict, or none. ``none`` is only
  valid with Secure, so Secure is forced on in that case.
"""
import logging

from starlette.responses import Response

from .. import config

logger = logging.getLogger(__name__)

SESSION_COOKIE = "session"
_VALID_SAMESITE = {"lax", "strict", "none"}


def samesite() -> str:
    value = (config.SESSION_COOKIE_SAMESITE or "lax").lower()
    if value not in _VALID_SAMESITE:
        logger.warning("Invalid SESSION_COOKIE_SAMESITE value; using 'lax'")
        return "lax"
    return value


def secure() -> bool:
    if samesite() == "none":
        return True
    if config.HOLOMED_ENV == "production" and not config.SESSION_COOKIE_SECURE:
        logger.warning("SESSION_COOKIE_SECURE is disabled in production")
    return bool(config.SESSION_COOKIE_SECURE)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(key=SESSION_COOKIE, value=token, httponly=True, secure=secure(),
                        samesite=samesite(), path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, secure=secure(),
                           samesite=samesite())
