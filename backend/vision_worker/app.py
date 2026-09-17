"""HoloMed private vision worker (deployed on a managed GPU, e.g. Modal).

Runs the exact validated local pipeline (backend.services.vision.inference)
behind a bearer token and returns VisionScreenResponse JSON. It is called only
by the HoloMed API (CloudVisionProvider), never by browsers.

- Images are processed in memory and never written to disk or logged.
- The model loads once from the SHA-256-verified checkpoint at
  VISION_WEIGHTS_PATH; VISION_PRELOAD=1 loads it at container start.
- Without VISION_WORKER_TOKEN every request is refused (503).
"""
import hmac
import logging
import threading
import time
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool

from .. import config
from ..services.vision.errors import (InvalidImageError, UnknownTargetError, UnsupportedImageError,
                                      VisionModelError)
from ..services.vision.schemas import VisionScreenResponse

logger = logging.getLogger("holomed.vision_worker")
_CHUNK = 1024 * 1024


def _require_token(request: Request) -> None:
    expected = (config.VISION_WORKER_TOKEN or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Worker is not configured")
    header = request.headers.get("authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    chunks, total = [], 0
    while chunk := await file.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413, detail="File too large")
        chunks.append(chunk)
    return b"".join(chunks)


def create_app() -> FastAPI:
    app = FastAPI(title="HoloMed Vision Worker", docs_url=None, redoc_url=None, openapi_url=None)
    state = {"load_error": False}

    def _preload():
        try:
            from ..services.vision.model import get_vision_model
            get_vision_model()
        except Exception:
            state["load_error"] = True
            logger.exception("Vision model preload failed")

    if config.VISION_PRELOAD:
        threading.Thread(target=_preload, name="vision-preload", daemon=True).start()

    @app.get("/v1/health", dependencies=[Depends(_require_token)])
    def health():
        from ..services.vision import model
        ready = model.is_loaded()
        return {"status": "ready" if ready else ("error" if state["load_error"] else "loading"),
                "model_ready": ready}

    @app.post("/v1/screen", response_model=VisionScreenResponse, dependencies=[Depends(_require_token)])
    async def screen(file: UploadFile = File(...), target: Optional[str] = Form(None)):
        data = await _read_limited(file, config.VISION_MAX_UPLOAD_BYTES)
        if not data:
            raise HTTPException(status_code=400, detail="Empty upload")
        from ..services.vision import inference
        started = time.perf_counter()
        try:
            result = await run_in_threadpool(inference.screen_image, data, target or None)
        except UnsupportedImageError as exc:
            raise HTTPException(status_code=415 if exc.media_type else 422, detail=str(exc))
        except InvalidImageError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except UnknownTargetError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except VisionModelError:
            logger.exception("Vision model unavailable")
            raise HTTPException(status_code=503, detail="Vision model is not available")
        except Exception:
            logger.exception("Vision screening failed")
            raise HTTPException(status_code=500, detail="Vision screening failed")
        logger.info("screen ok format=%s target=%s total_ms=%.0f",
                    result.input.format, result.explanation.target_pathology,
                    (time.perf_counter() - started) * 1000)
        return result

    return app
