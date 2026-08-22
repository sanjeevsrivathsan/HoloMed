import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .database import init_db
from .routers import health, medical_data
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

# Initialise the SQLite DB on startup
@app.on_event("startup")
async def on_startup():
    init_db()

# Include versioned API router
app.include_router(health.router, prefix="/api/v1")
app.include_router(medical_data.router)
@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "HoloMed AI backend",
        "version": "0.1.0",
    }
