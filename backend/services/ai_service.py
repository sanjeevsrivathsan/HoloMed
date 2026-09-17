import json
import logging
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from fastapi import HTTPException

async def generate_summary(text: str, mode: str, ollama_url: str = None) -> List[Dict[str, Any]]:
    """
    Attempts to generate a summary using a local Ollama instance.
    Raises HTTPException if Ollama is unreachable or generation fails.
    """
    url = (ollama_url or OLLAMA_BASE_URL).rstrip("/")
    model = OLLAMA_MODEL or "qwen3:8b"
    prompt = f"Summarize the following medical report in {mode} mode:\n\n{text}\n\nReturn ONLY a JSON array of objects with keys: key, label, content, visible (boolean)."
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json"
                }
            )
            response.raise_for_status()
            result = response.json()
            generated_text = result.get("response", "[]")
            
            # Attempt to parse the JSON array
            summary_json = json.loads(generated_text)
            if isinstance(summary_json, list) and len(summary_json) > 0:
                return summary_json
    except Exception as e:
        logger.error(f"Ollama generation failed ({e})")
        raise HTTPException(status_code=503, detail="AI Summarization service is currently unavailable.")
        
    raise HTTPException(status_code=500, detail="Failed to parse AI summary response.")
