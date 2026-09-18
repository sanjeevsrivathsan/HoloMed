import os
from fastapi import FastAPI
import logging
from .logger import configure_logger
configure_logger("backend")  # INFO-level, non-sensitive service logs (no images, tokens or identifiers)
logger = logging.getLogger(__name__)
from .services.google_oauth import install_access_log_redaction
install_access_log_redaction()  # keep OAuth callback codes/state out of access logs
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routers import health, medical_data, dicomweb, auth
# Load environment variables (requires python-dotenv if .env exists)
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv('.env')  # the working-directory .env (see backend/config.py)

app = FastAPI(
    title="HoloMed AI",
    description="Medical Intelligence & Visualization Platform",
    version="0.1.0",
    # No lifespan needed for simple init
)

# CORS configuration – allow origins from env or default to localhost dev front‑end
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "worker-src 'self' blob:; "
            "media-src 'self' blob:; "
            "frame-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)


# Initialise the SQLite DB on startup
@app.on_event("startup")
async def on_startup():
    # Validate required JWT secret
    if not os.getenv("JWT_SECRET"):
        raise RuntimeError("JWT_SECRET environment variable is required for authentication")
    # Check for stray duplicate SQLite databases and warn if found (do not delete automatically).
    stray_db_path = os.path.join(os.path.dirname(__file__), "data", "holomed.db")
    prod_db_path = os.path.abspath(os.getenv('HOLUMED_DB_PATH', './data/holomed.db'))
    if os.path.isfile(stray_db_path) and os.path.abspath(stray_db_path) != prod_db_path:
        logger.warning(f"Found stray SQLite database at {stray_db_path}. It is not used by the application."
                       f" Please verify if it should be removed manually.")
    # Initialise the SQLite DB
    init_db()
    # Optional: warm the vision model in the background (VISION_PRELOAD=1)
    from .services.vision.provider import start_background_preload
    start_background_preload()

# Include versioned API router
app.include_router(health.router, prefix="/api/v1")
app.include_router(medical_data.router)
app.include_router(auth.router)
app.include_router(dicomweb.router)
app.include_router(dicomweb.patient_router)
from .routers import patients
app.include_router(patients.router)
from .routers import report, audit, measurement, template, consent, storage_connection, search, ai
app.include_router(report.router)
app.include_router(ai.router)
app.include_router(audit.router)
app.include_router(measurement.router)
app.include_router(template.router)
app.include_router(consent.router)
app.include_router(storage_connection.router)
app.include_router(search.router)
from .routers import vision
app.include_router(vision.router)
from .routers import demo
app.include_router(demo.router)
import sys
from fastapi import Depends
from backend.dependencies import auth as auth_dep
from backend.models import User
from backend.services.auth_service import create_access_token





# Serve OHIF static build at /ohif (config: routerBasename "/ohif/" in frontend/ohif/app-config.js)
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException


OHIF_DIR = "frontend/ohif"
_APP_CONFIG_TAG = 'src="/ohif/app-config.js"'


def ohif_index_response():
    """OHIF's index.html, pointing at app-config.js?v=<content hash>.

    app-config.js (the data sources) keeps its name across changes, so a browser could keep using
    a cached old copy: OHIF then starts without the `holomed` data source and renders an empty
    black page without requesting any data. Versioning the URL by content means a changed config
    is always fetched; the HTML itself is never stored so it always names the current version.
    """
    import hashlib
    from fastapi.responses import HTMLResponse
    with open(os.path.join(OHIF_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(OHIF_DIR, "app-config.js"), "rb") as f:
        version = hashlib.sha256(f.read()).hexdigest()[:16]
    if _APP_CONFIG_TAG not in html:
        logger.warning("OHIF index.html has no %s tag; app-config.js is not versioned", _APP_CONFIG_TAG)
    html = html.replace(_APP_CONFIG_TAG, f'src="/ohif/app-config.js?v={version}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


class SPAStaticFiles(StaticFiles):
    """Static files with a single-page-app fallback: client-side routes such as
    /ohif/viewer?StudyInstanceUIDs=… (deep links, browser refresh) get index.html.
    Paths that look like files (have an extension) still return 404 when missing.

    Every response is `Cache-Control: no-cache`: the browser must revalidate (cheap 304s), so a
    cached copy of the viewer or of app-config.js (its data sources) can never outlive a change."""

    async def get_response(self, path, scope):
        if path in ("", ".", "index.html"):
            return ohif_index_response()
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in os.path.basename(path):
                raise
            return ohif_index_response()
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/ohif", SPAStaticFiles(directory="frontend/ohif", html=True), name="ohif")
@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "HoloMed AI backend",
        "version": "0.1.0",
    }
