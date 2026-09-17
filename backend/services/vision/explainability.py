"""Class-specific Grad-CAM for the DenseNet-121 model (validated in Phase 2).

Target layer is ``features.denseblock4``. ``features.norm5`` is not used: the
TorchXRayVision forward applies an in-place ReLU to the norm5 output, which is
incompatible with full backward hooks.

Rendering uses numpy + PIL only (no matplotlib).
"""
import base64
import io
from dataclasses import dataclass
from typing import Tuple

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from .constants import TARGET_LAYER  # noqa: F401  (re-exported)


@dataclass
class GradCamResult:
    cam: np.ndarray               # float32 [H, W] in [0, 1], model input space
    target_index: int
    target_score: float           # score recomputed in the gradient pass
    activation_shape: Tuple[int, ...]
    gradient_norm: float
    cam_raw_max: float


def target_layer(model: torch.nn.Module) -> torch.nn.Module:
    return model.features.denseblock4


def grad_cam(model: torch.nn.Module, x: torch.Tensor, target_index: int) -> GradCamResult:
    """Grad-CAM for one model output. Caller must hold the model lock."""
    if not 0 <= target_index < len(model.pathologies):
        raise ValueError(f"target_index {target_index} is not a model output")
    layer = target_layer(model)
    activations, gradients = [], []
    h1 = layer.register_forward_hook(lambda _m, _i, out: activations.append(out))
    h2 = layer.register_full_backward_hook(lambda _m, _gi, gout: gradients.append(gout[0]))
    try:
        with torch.enable_grad():
            xin = x.detach().clone().requires_grad_(True)
            model.zero_grad(set_to_none=True)
            out = model(xin)
            out[0, target_index].backward()
    finally:
        h1.remove()
        h2.remove()
        model.zero_grad(set_to_none=True)
    act, grad = activations[0].detach(), gradients[0].detach()
    alpha = torch.mean(grad, dim=(2, 3), keepdim=True)
    cam = F.relu(torch.sum(alpha * act, dim=1, keepdim=True))
    cam = F.interpolate(cam, size=x.shape[-2:], mode="bilinear", align_corners=False)
    cam_np = cam[0, 0].cpu().numpy()
    lo, hi = float(cam_np.min()), float(cam_np.max())
    cam_norm = (cam_np - lo) / (hi - lo) if hi > lo else np.zeros_like(cam_np)
    return GradCamResult(
        cam=cam_norm.astype(np.float32),
        target_index=target_index,
        target_score=float(out[0, target_index].detach().item()),
        activation_shape=tuple(act.shape),
        gradient_norm=float(grad.norm().item()),
        cam_raw_max=hi,
    )


def apply_jet_colormap(cam_normalized: np.ndarray) -> np.ndarray:
    """JET colormap: float [0, 1] -> RGB uint8 (same as the validation scripts)."""
    x = np.clip(cam_normalized, 0.0, 1.0)
    r = np.clip(1.5 - np.abs(x * 4.0 - 3.0), 0.0, 1.0)
    g = np.clip(1.5 - np.abs(x * 4.0 - 2.0), 0.0, 1.0)
    b = np.clip(1.5 - np.abs(x * 4.0 - 1.0), 0.0, 1.0)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def render_original(display: np.ndarray, crop: Tuple[int, int, int], max_side: int) -> np.ndarray:
    """Grayscale center-cropped region the model saw, at most ``max_side`` pixels.

    This is the image the heatmap and overlay are aligned to (browsers cannot
    render DICOM, so the API returns it for every input format).
    """
    y0, x0, size = crop
    region = Image.fromarray(display[y0:y0 + size, x0:x0 + size])
    side = min(size, max_side)
    if side != size:
        region = region.resize((side, side), Image.BILINEAR)
    return np.asarray(region)


def render_overlay(original: np.ndarray, cam: np.ndarray) -> np.ndarray:
    """Blend the heatmap onto the rendered original (0.55 image + 0.45 JET).

    ``original`` comes from :func:`render_original`, so the overlay is capped at
    the same size; Phase 2 rendered at native resolution.
    """
    side = original.shape[0]
    cam_img = Image.fromarray(cam).resize((side, side), Image.BILINEAR)
    heat = apply_jet_colormap(np.asarray(cam_img))
    base = original.astype(np.float32)[:, :, None]
    return (0.55 * base + 0.45 * heat).astype(np.uint8)


def png_base64(pixels: np.ndarray) -> str:
    """PNG (grayscale for 2D arrays, RGB for HxWx3) as base64."""
    buf = io.BytesIO()
    Image.fromarray(pixels).save(buf, format="PNG", compress_level=1)  # lossless; favors speed
    return base64.b64encode(buf.getvalue()).decode("ascii")
