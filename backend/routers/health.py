from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from ..database import engine

router = APIRouter()

@router.get("/ready", tags=["Health"])
def readiness_check():
    """Check DB connectivity and return ready status.
    Returns 200 with {"status":"ok"} if the configured database is reachable.
    Returns 503 with Service Unavailable otherwise.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        print(f"Readiness check failed: {exc}")
        raise HTTPException(status_code=503, detail="Service Unavailable")

@router.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy"}
