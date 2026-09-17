"""Vision provider selection.

The router depends only on ``VisionProvider.screen``; which backend runs the
model is configuration (``VISION_PROVIDER``), invisible to API clients.

- ``local`` (default): the validated in-process TorchXRayVision implementation.
  It is the reference implementation and the fallback.
- ``cloud``: reserved for running the same model/weights on managed GPU
  infrastructure. Not implemented; selecting it makes the endpoint return 503
  rather than silently using another model.

Importing this module does not import torch.
"""
from typing import Optional, Protocol

from ... import config
from .schemas import VisionScreenResponse


class VisionProviderUnavailable(RuntimeError):
    """The configured provider cannot serve requests (HTTP 503)."""


class VisionProvider(Protocol):
    name: str

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        ...


class LocalVisionProvider:
    name = "local"

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        from . import inference  # torch is imported on first use only
        return inference.screen_image(data, target)


class CloudVisionProvider:
    """Placeholder for a managed-GPU deployment of the same validated model.

    A real implementation must return the same ``VisionScreenResponse`` schema,
    verify the same weights SHA-256, and keep uploads out of logs.
    """
    name = "cloud"

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        raise VisionProviderUnavailable("Cloud vision provider is not configured")


_PROVIDERS = {"local": LocalVisionProvider, "cloud": CloudVisionProvider}


def start_background_preload() -> bool:
    """Load the local model in a daemon thread so the first request is fast.

    Opt-in via VISION_PRELOAD=1. Never blocks or fails application startup;
    a load failure is logged and requests then return 503 as usual.
    """
    if not config.VISION_PRELOAD or (config.VISION_PROVIDER or "local").strip().lower() != "local":
        return False
    import logging
    import threading

    def _load():
        try:
            from .model import get_vision_model
            get_vision_model()
        except Exception:
            logging.getLogger(__name__).exception("Vision model preload failed")

    threading.Thread(target=_load, name="vision-preload", daemon=True).start()
    return True


def get_vision_provider() -> VisionProvider:
    key = (config.VISION_PROVIDER or "local").strip().lower()
    cls = _PROVIDERS.get(key)
    if cls is None:
        raise VisionProviderUnavailable(f"Unknown VISION_PROVIDER {key!r}")
    return cls()
