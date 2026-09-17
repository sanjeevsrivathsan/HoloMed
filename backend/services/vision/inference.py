"""Screening orchestration: preprocess -> model scores -> Grad-CAM -> response.

Model scores are the TorchXRayVision outputs used directly. The model's forward
already applies sigmoid + op_norm, so no further transformation is applied.
"""
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import torch

from ... import config
from . import explainability
from .model import (ARCHITECTURE, INPUT_SIZE, MODEL_NAME, WEIGHTS_ID, VisionModel,
                    get_vision_model)
from .preprocessing import preprocess
from .schemas import (EncodedImage, VisionExplanation, VisionFinding, VisionInputInfo,
                      VisionModelInfo, VisionScreenResponse, VisionTiming)


class UnknownTargetError(ValueError):
    """Requested Grad-CAM target is not one of the model outputs."""


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def model_scores(vm: VisionModel, x: torch.Tensor) -> Dict[str, float]:
    """All model outputs for a preprocessed [1,1,224,224] tensor on the model device."""
    with torch.no_grad():
        out = vm.module(x)
    scores = out[0].detach().cpu()
    if scores.numel() != len(vm.targets) or not torch.isfinite(scores).all():
        raise RuntimeError("Model produced invalid outputs")
    return {name: float(v) for name, v in zip(vm.targets, scores.tolist())}


def select_target(scores: Dict[str, float], targets: List[str], requested: Optional[str]) -> int:
    if requested:
        if requested not in targets:
            raise UnknownTargetError(f"Unknown target pathology {requested!r}")
        return targets.index(requested)
    # Highest-scoring output; ties resolved by model output order.
    return max(range(len(targets)), key=lambda i: (scores[targets[i]], -i))


def model_info(vm: VisionModel) -> VisionModelInfo:
    return VisionModelInfo(name=MODEL_NAME, architecture=ARCHITECTURE, weights=WEIGHTS_ID,
                           weight_sha256=vm.weight_sha256, targets=len(vm.targets),
                           target_list=list(vm.targets), device=vm.device_name,
                           input_size=INPUT_SIZE)


def screen_image(data: bytes, target: Optional[str] = None,
                 vm: Optional[VisionModel] = None) -> VisionScreenResponse:
    t_start = time.perf_counter()
    vm = vm or get_vision_model()
    if target is not None and target not in vm.targets:
        raise UnknownTargetError(f"Unknown target pathology {target!r}")

    t0 = time.perf_counter()
    pre = preprocess(data)
    preprocessing_ms = (time.perf_counter() - t0) * 1000

    with vm.lock:
        x = pre.tensor.to(vm.device, non_blocking=False)
        _sync(vm.device)
        t0 = time.perf_counter()
        scores = model_scores(vm, x)
        _sync(vm.device)
        inference_ms = (time.perf_counter() - t0) * 1000

        idx = select_target(scores, vm.targets, target)
        t0 = time.perf_counter()
        cam = explainability.grad_cam(vm.module, x, idx)
        _sync(vm.device)
        gradcam_ms = (time.perf_counter() - t0) * 1000
    inferred_at = datetime.now(timezone.utc)

    t0 = time.perf_counter()
    heat_rgb = explainability.apply_jet_colormap(cam.cam)
    original_gray = explainability.render_original(pre.display, pre.crop,
                                                   config.VISION_MAX_OVERLAY_SIDE)
    overlay_rgb = explainability.render_overlay(original_gray, cam.cam)
    heatmap = EncodedImage(width=heat_rgb.shape[1], height=heat_rgb.shape[0],
                           data=explainability.png_base64(heat_rgb))
    original = EncodedImage(width=original_gray.shape[1], height=original_gray.shape[0],
                            data=explainability.png_base64(original_gray))
    overlay = EncodedImage(width=overlay_rgb.shape[1], height=overlay_rgb.shape[0],
                           data=explainability.png_base64(overlay_rgb))
    rendering_ms = (time.perf_counter() - t0) * 1000

    findings = sorted((VisionFinding(pathology=p, score=s) for p, s in scores.items()),
                      key=lambda f: f.score, reverse=True)
    target_name = vm.targets[idx]
    dec = pre.decoded
    return VisionScreenResponse(
        model=model_info(vm),
        input=VisionInputInfo(format=dec.format, width=int(dec.pixels.shape[1]),
                              height=int(dec.pixels.shape[0]), source_mode=dec.source_mode,
                              bits_stored=dec.bits_stored, modality=dec.modality,
                              transfer_syntax=dec.transfer_syntax, preprocessing=pre.steps),
        primary_finding=findings[0],  # highest model score (stable sort keeps output order on ties)
        findings=findings,
        explanation=VisionExplanation(target_pathology=target_name,
                                      target_score=scores[target_name],
                                      target_layer=explainability.TARGET_LAYER,
                                      original=original, heatmap=heatmap, overlay=overlay),
        timing=VisionTiming(preprocessing_ms=round(preprocessing_ms, 3),
                            inference_ms=round(inference_ms, 3),
                            gradcam_ms=round(gradcam_ms, 3),
                            rendering_ms=round(rendering_ms, 3),
                            total_ms=round((time.perf_counter() - t_start) * 1000, 3)),
        inferred_at=inferred_at,
    )
