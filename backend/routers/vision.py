import logging
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import Session

from .. import config
from ..database import get_session
from ..dependencies.auth import get_current_user
from ..models import User
from ..services.explanation import cxr_explanation
from ..services.vision import results
from ..services.vision.errors import (InvalidImageError, UnknownTargetError, UnsupportedImageError,
                                      VisionModelError, VisionProviderUnavailable)
from ..services.vision.provider import get_vision_provider, provider_key
from ..services.vision.schemas import VisionScreenResponse
from .medical_data import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vision", tags=["Vision AI"])

_CHUNK = 1024 * 1024
EXPLANATION_UNAVAILABLE = ("AI explanation is temporarily unavailable. The screening result and "
                           "visual explanation remain available for clinical review.")


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Read the upload into memory, rejecting it as soon as it exceeds ``limit``."""
    chunks, total = [], 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(status_code=413,
                                detail=f"File too large: limit is {limit // (1024 * 1024)} MiB")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/screen", response_model=VisionScreenResponse)
async def screen(
    file: UploadFile = File(..., description="Chest radiograph: PNG, JPEG, or DICOM"),
    target: Optional[str] = Form(None, description="Optional Grad-CAM target; must be a model output"),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Chest radiograph screening assistance with a Grad-CAM visual explanation.

    The upload is processed in memory and not stored. Scores are model scores,
    not diagnoses; every response carries the safety notice.
    """
    data = await _read_limited(file, config.VISION_MAX_UPLOAD_BYTES)
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")

    started = time.perf_counter()
    try:
        provider = get_vision_provider()
        result = await run_in_threadpool(provider.screen, data, target or None)
    except VisionProviderUnavailable as exc:
        logger.warning("Vision provider unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Vision service is not available")
    except ImportError:
        # The local provider imports torch lazily; the backend runs without it.
        logger.exception("Vision stack is not installed")
        raise HTTPException(status_code=503, detail="Vision service is not available")
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

    scores = {f.pathology: f.score for f in result.findings}
    result.result_id = results.register(user.id, scores, result.primary_finding.pathology,
                                        result.model.weights, result.model.weight_sha256)
    logger.info("vision_screen provider=%s format=%s target=%s ms=%.0f",
                provider.name, result.input.format, result.explanation.target_pathology,
                (time.perf_counter() - started) * 1000)
    log_action(session, user.id, "vision_screen", {
        "input_format": result.input.format,
        "weights": result.model.weights,
        "target_pathology": result.explanation.target_pathology,
    })
    session.commit()
    return result


class ExplanationRequest(BaseModel):
    result_id: str = Field(..., min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    target: str = Field(..., min_length=1, max_length=64)


@router.post("/explanations", response_model=cxr_explanation.TextExplanationResponse)
async def explain(
    body: ExplanationRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Language-model explanation of one model output of a screening result.

    Uses only the structured result stored by /screen (never the image). If the
    text AI is unavailable the screening result is unaffected; this returns 503.
    """
    try:
        response = await run_in_threadpool(cxr_explanation.explain, body.result_id, user.id, body.target)
    except cxr_explanation.ExplanationNotFound:
        raise HTTPException(status_code=404, detail="Screening result not found or expired")
    except cxr_explanation.ExplanationUnavailable:
        raise HTTPException(status_code=503, detail=EXPLANATION_UNAVAILABLE)
    except Exception:
        logger.exception("Explanation failed")
        raise HTTPException(status_code=503, detail=EXPLANATION_UNAVAILABLE)
    if not response.cached:
        log_action(session, user.id, "vision_explanation", {"target_pathology": response.target_pathology})
        session.commit()
    return response


_status_cache = {"at": 0.0, "value": None}
_status_lock = threading.Lock()
STATUS_CACHE_SECONDS = 10.0


@router.get("/status")
async def status():
    """Readiness of the vision service (no credentials or infrastructure details)."""
    with _status_lock:
        cached = _status_cache["value"]
        if cached is not None and time.monotonic() - _status_cache["at"] < STATUS_CACHE_SECONDS:
            return cached
    key = provider_key()
    try:
        provider = get_vision_provider()
        info = await run_in_threadpool(provider.status)
    except VisionProviderUnavailable:
        info = {"configured": False, "model_ready": False}
    value = {
        "provider": key if key in ("local", "cloud") else "unknown",
        "provider_configured": bool(info.get("configured")),
        "model_ready": bool(info.get("model_ready")),
        "status": ("ready" if info.get("model_ready")
                   else "unavailable" if not info.get("configured")
                   else "loading" if key == "cloud" or config.VISION_PRELOAD
                   else "standby"),  # local model loads on first request
    }
    with _status_lock:
        _status_cache.update(at=time.monotonic(), value=value)
    return value
