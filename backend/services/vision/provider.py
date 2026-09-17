"""Vision provider selection.

The router depends only on ``VisionProvider.screen``; which backend runs the
model is configuration (``VISION_PROVIDER``), invisible to API clients.

- ``local`` (default, primary deployment): the validated in-process
  TorchXRayVision implementation on this machine's GPU (CPU fallback). Needs no
  cloud credentials or network access.
- ``cloud`` (optional): the same code and weights running in the private GPU
  worker (backend/vision_worker, deployed on Modal); see ``cloud.py``.

There is deliberately no fallback between providers: if ``cloud`` is selected
and unavailable, requests fail with 503 instead of silently running elsewhere.

Importing this module does not import torch.
"""
import logging
import os
import threading
from typing import Optional, Protocol

from ... import config
from .cloud import CloudVisionProvider
from .errors import VisionModelError, VisionProviderUnavailable  # noqa: F401  (re-exported)
from .schemas import VisionScreenResponse

logger = logging.getLogger(__name__)


class VisionProvider(Protocol):
    name: str

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        ...

    def status(self) -> dict:
        ...


class LocalVisionProvider:
    name = "local"

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        from . import inference  # torch is imported on first use only
        return inference.screen_image(data, target)

    def status(self) -> dict:
        configured = os.path.isfile(config.VISION_WEIGHTS_PATH)
        accelerator = None
        try:
            from . import model
            ready = model.is_loaded()
            device_type = model.loaded_device_type()
            if device_type is None and configured:
                device_type = model.resolve_device(config.VISION_DEVICE).type
            accelerator = {"cuda": "gpu", "cpu": "cpu"}.get(device_type)
        except ImportError:
            configured, ready = False, False
        except VisionModelError:
            ready = False  # e.g. VISION_DEVICE=cuda without CUDA
        return {"configured": configured, "model_ready": ready, "accelerator": accelerator}


_PROVIDERS = {"local": LocalVisionProvider, "cloud": CloudVisionProvider}


def provider_key() -> str:
    return (config.VISION_PROVIDER or "local").strip().lower()


def start_background_preload() -> bool:
    """Load the local model in a daemon thread so the first request is fast.

    Opt-in via VISION_PRELOAD=1. Never blocks or fails application startup;
    a load failure is logged and requests then return 503 as usual. With the
    cloud provider the remote worker preloads itself.
    """
    if not config.VISION_PRELOAD or provider_key() != "local":
        return False

    def _load():
        try:
            from .model import get_vision_model
            get_vision_model()
        except Exception:
            logger.exception("Vision model preload failed")

    threading.Thread(target=_load, name="vision-preload", daemon=True).start()
    return True


def get_vision_provider() -> VisionProvider:
    cls = _PROVIDERS.get(provider_key())
    if cls is None:
        raise VisionProviderUnavailable("Unknown VISION_PROVIDER value")
    return cls()
