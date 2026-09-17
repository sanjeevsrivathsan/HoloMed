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


@router.get("/status")
async def get_text_ai_status(current_user=Depends(auth_dep.get_current_user)):
    """Text AI provider readiness for Settings (no URLs, keys or infrastructure details)."""
    from backend import config
    from backend.services.text_ai.providers import TextAIUnavailable, get_text_ai_provider

    key = (config.TEXT_AI_PROVIDER or "ollama").strip().lower()
    try:
        provider = get_text_ai_provider()
    except TextAIUnavailable:
        return {"provider": key if key in ("ollama", "omniroute") else "unknown", "model": None,
                "status": "not_configured"}
    if provider.name != "ollama":
        # Hosted gateway: configured, not probed from here.
        return {"provider": provider.name, "model": provider.model, "status": "configured"}
    status = "not_running"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{provider.base}/api/tags")
        if response.status_code == 200:
            names = [m.get("name", "") for m in response.json().get("models", [])]
            status = "connected" if any(n == provider.model or n.startswith(provider.model) for n in names) \
                else "model_missing"
    except (httpx.HTTPError, ValueError):
        pass
    return {"provider": "ollama", "model": provider.model, "status": status}
