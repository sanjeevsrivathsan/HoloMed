import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from .. import config
from ..database import get_session
from ..dependencies.auth import get_current_user
from ..models import User
from ..services.vision.provider import VisionProviderUnavailable, get_vision_provider
from ..services.vision.schemas import VisionScreenResponse
from .medical_data import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/vision", tags=["Vision AI"])

_CHUNK = 1024 * 1024


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

    # Imported lazily so the backend starts even where the vision stack is absent.
    try:
        from ..services.vision import inference, model, preprocessing
    except ImportError:
        logger.exception("Vision stack is not installed")
        raise HTTPException(status_code=503, detail="Vision service is not available")

    try:
        provider = get_vision_provider()
        result = await run_in_threadpool(provider.screen, data, target or None)
    except VisionProviderUnavailable:
        logger.exception("Vision provider unavailable")
        raise HTTPException(status_code=503, detail="Vision service is not available")
    except preprocessing.UnsupportedImageError as exc:
        raise HTTPException(status_code=415 if exc.media_type else 422, detail=str(exc))
    except preprocessing.InvalidImageError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except inference.UnknownTargetError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except model.VisionModelError:
        logger.exception("Vision model unavailable")
        raise HTTPException(status_code=503, detail="Vision model is not available")
    except Exception:
        logger.exception("Vision screening failed")
        raise HTTPException(status_code=500, detail="Vision screening failed")

    log_action(session, user.id, "vision_screen", {
        "input_format": result.input.format,
        "weights": result.model.weights,
        "target_pathology": result.explanation.target_pathology,
    })
    session.commit()
    return result
