from fastapi import APIRouter, Depends, HTTPException
import httpx
from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from backend.dependencies import auth as auth_dep

router = APIRouter(prefix="/api/v1/ai", tags=["AI"])

@router.get("/ollama/config")
async def get_ollama_config(current_user=Depends(auth_dep.get_current_user)):
    url = OLLAMA_BASE_URL.rstrip("/")
    model = OLLAMA_MODEL or "qwen3:8b"
    
    available = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{url}/api/tags")
            if response.status_code == 200:
                tags = response.json().get("models", [])
                if any(m.get("name") == model or m.get("name").startswith(model) for m in tags):
                    available = True
    except Exception:
        pass

    return {
        "baseUrl": url,
        "model": model,
        "available": available
    }
