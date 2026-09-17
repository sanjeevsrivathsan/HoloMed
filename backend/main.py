import os
from fastapi import FastAPI
import logging
logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routers import health, medical_data, dicomweb, auth
# Load environment variables (requires python-dotenv if .env exists)
if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

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
import sys
from fastapi import Depends
from backend.dependencies import auth as auth_dep
from backend.models import User
from backend.services.auth_service import create_access_token





# Serve OHIF static build at /ohif
from fastapi.staticfiles import StaticFiles
app.mount("/ohif", StaticFiles(directory="frontend/ohif", html=True), name="ohif")
@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "HoloMed AI backend",
        "version": "0.1.0",
    }
