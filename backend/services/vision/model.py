"""Validated chest radiograph model: TorchXRayVision DenseNet-121 (densenet121-res224-all).

The model is loaded once per process from the local, hash-verified checkpoint.
TorchXRayVision's own constructor is not used with ``weights=...`` because it
downloads the checkpoint when its cache copy is missing; here the architecture is
built locally and the state dict is loaded from the verified file instead.
The resulting module is the same class with the same attributes
(targets, op_threshs, input_resolution) as ``xrv.models.DenseNet(weights=...)``.
"""
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

import torch
import torchxrayvision as xrv

from ... import config

logger = logging.getLogger(__name__)

MODEL_NAME = "TorchXRayVision DenseNet-121"
ARCHITECTURE = "DenseNet-121 (growth 32, blocks 6/12/24/16, 1 input channel, 18 outputs)"
WEIGHTS_ID = "densenet121-res224-all"
EXPECTED_SHA256 = "56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899"
EXPECTED_TARGETS = [
    "Atelectasis", "Consolidation", "Infiltration", "Pneumothorax", "Edema",
    "Emphysema", "Fibrosis", "Effusion", "Pneumonia", "Pleural_Thickening",
    "Cardiomegaly", "Nodule", "Mass", "Hernia", "Lung Lesion", "Fracture",
    "Lung Opacity", "Enlarged Cardiomediastinum",
]
INPUT_SIZE = 224


class VisionModelError(RuntimeError):
    """The model cannot be made available (missing/altered checkpoint, bad device)."""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_device(requested: str) -> torch.device:
    requested = (requested or "auto").lower()
    if requested == "auto":
        return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if requested.startswith("cuda"):
        if not torch.cuda.is_available():
            raise VisionModelError("VISION_DEVICE requests CUDA but CUDA is not available")
        return torch.device("cuda:0" if requested == "cuda" else requested)
    if requested == "cpu":
        return torch.device("cpu")
    raise VisionModelError(f"Unsupported VISION_DEVICE value: {requested!r}")


@dataclass
class VisionModel:
    """A loaded model plus the lock that serializes its use.

    Why the lock: Grad-CAM registers forward/backward hooks on a shared layer,
    zeroes and accumulates parameter gradients, and runs a backward pass. Two
    requests interleaving on the same module would mix hook captures and
    gradients. Inference and Grad-CAM for one request therefore run under this
    lock; decoding, preprocessing and PNG rendering run outside it.
    """
    module: torch.nn.Module
    device: torch.device
    weight_sha256: str
    targets: List[str]
    load_ms: float
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def device_name(self) -> str:
        if self.device.type == "cuda":
            return f"{self.device} ({torch.cuda.get_device_name(self.device)})"
        return "cpu"


def _warm_up(model: torch.nn.Module, dev: torch.device) -> None:
    """One forward + backward pass so the first request does not pay CUDA start-up.

    Uses a horizontal ramp spanning the normalized range [-1024, 1024]; the
    output is discarded and gradients are cleared.
    """
    ramp = torch.linspace(-1024.0, 1024.0, INPUT_SIZE, device=dev)
    x = ramp.expand(1, 1, INPUT_SIZE, INPUT_SIZE).contiguous()
    with torch.no_grad():
        model(x)
    model(x)[0, 0].backward()
    model.zero_grad(set_to_none=True)
    if dev.type == "cuda":
        torch.cuda.synchronize(dev)


def load_model(weights_path: Optional[str] = None, device: Optional[str] = None) -> VisionModel:
    """Build DenseNet-121 and load the verified local checkpoint (no network access)."""
    path = weights_path or config.VISION_WEIGHTS_PATH
    dev = resolve_device(device or config.VISION_DEVICE)
    t0 = time.perf_counter()
    try:
        digest = sha256_file(path)
    except OSError as exc:
        raise VisionModelError("Vision model checkpoint is not available") from exc
    # Verify before deserializing: the checkpoint is a full pickle (weights_only=False).
    if digest != EXPECTED_SHA256:
        raise VisionModelError("Vision model checkpoint failed SHA-256 verification")

    spec = xrv.models.model_urls[WEIGHTS_ID]
    model = xrv.models.DenseNet(num_classes=len(spec["labels"]))
    saved = torch.load(path, map_location="cpu", weights_only=False)
    for mod in saved.modules():  # same patch as xrv for old pickled modules
        if not hasattr(mod, "_non_persistent_buffers_set"):
            mod._non_persistent_buffers_set = set()
    model.load_state_dict(saved.state_dict())
    del saved
    model.weights = WEIGHTS_ID
    model.targets = list(spec["labels"])
    model.pathologies = model.targets
    model.op_threshs = torch.tensor(spec["op_threshs"])
    model.input_resolution = spec["input_resolution"]
    model.apply_sigmoid = False
    model.to(dev).eval()
    for p in model.parameters():
        p.requires_grad_(True)

    if list(model.pathologies) != EXPECTED_TARGETS:
        raise VisionModelError("Vision model target list does not match the validated list")
    if model.op_threshs is None or torch.isnan(model.op_threshs).any():
        raise VisionModelError("Vision model operating thresholds are missing")
    load_ms = (time.perf_counter() - t0) * 1000
    _warm_up(model, dev)
    logger.info("Vision model %s loaded on %s in %.1f ms (sha256 verified)", WEIGHTS_ID, dev, load_ms)
    return VisionModel(module=model, device=dev, weight_sha256=digest,
                       targets=list(model.pathologies), load_ms=load_ms)


_instance: Optional[VisionModel] = None
_instance_lock = threading.Lock()


def get_vision_model() -> VisionModel:
    """Process-wide singleton; the model is loaded on first use, once."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = load_model()
    return _instance


def reset_vision_model() -> None:
    """Drop the singleton (tests only)."""
    global _instance
    with _instance_lock:
        _instance = None
