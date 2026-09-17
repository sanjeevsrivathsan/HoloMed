"""HoloMed Chest X-Ray AI — Phase 2 Real Chest X-Ray Validation.

Runs verified public/de-identified chest radiographs (see
artifacts/real_cxr/provenance.json) through ingestion, preprocessing,
TorchXRayVision DenseNet-121 (densenet121-res224-all), all 18 model outputs,
and class-specific Grad-CAM, then writes validation artifacts.

Research/engineering validation only — not a diagnostic result.

Run:  PYTHONIOENCODING=utf-8 python backend/tests/validate_real_cxr.py
"""
import os
import sys
import json
import time
import hashlib
import platform
import warnings

import numpy as np
import pandas as pd
import pydicom
import torch
import torch.nn.functional as F
import torchxrayvision as xrv
from PIL import Image, ImageDraw, ImageFont
from pydicom.pixels import apply_modality_lut, apply_voi_lut

# Composite is drawn with PIL: on this machine an Application Control policy
# blocks matplotlib's compiled _image extension.
sys.path.insert(0, os.path.dirname(__file__))
from validate_model import WEIGHTS, apply_jet_colormap  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "artifacts", "real_cxr")
PROVENANCE = os.path.join(OUT, "provenance.json")
XRV_DATA = os.path.join(os.path.dirname(xrv.__file__), "data")

WEIGHTS_ID = "densenet121-res224-all"
EXPECTED_WEIGHTS_SHA256 = "56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899"
EXPECTED_PATHOLOGIES = [
    "Atelectasis", "Consolidation", "Infiltration", "Pneumothorax", "Edema",
    "Emphysema", "Fibrosis", "Effusion", "Pneumonia", "Pleural_Thickening",
    "Cardiomegaly", "Nodule", "Mass", "Hernia", "Lung Lesion", "Fracture",
    "Lung Opacity", "Enlarged Cardiomediastinum",
]
# Same layer as Phase 1. features.norm5 is not used: features2() applies an
# in-place ReLU to its output, which conflicts with full backward hooks.
GRADCAM_LAYER = "features.denseblock4"
INPUT_SIZE = 224
WARMUP, N_INFER, N_CAM, N_CPU = 20, 100, 20, 20
BANNER = "Research/Engineering Validation — Not a Diagnostic Result"

# Required Phase 2 names apply to the primary case; secondary cases are prefixed.
CASE_PREFIX = {"nih_png": "", "siim_dicom": "siim_dicom_"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def stats(ms):
    a = np.asarray(ms)
    return {"n": int(a.size), "mean_ms": round(float(a.mean()), 3),
            "median_ms": round(float(np.median(a)), 3),
            "p95_ms": round(float(np.percentile(a, 95)), 3),
            "min_ms": round(float(a.min()), 3), "max_ms": round(float(a.max()), 3)}


def cuda_sync(device):
    if device.type == "cuda":
        torch.cuda.synchronize(device)


class Checks:
    def __init__(self):
        self.items = []

    def add(self, name, ok, detail=""):
        self.items.append({"check": name, "pass": bool(ok), "detail": str(detail)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
        return bool(ok)

    @property
    def passed(self):
        return all(i["pass"] for i in self.items)


# ── Ingestion ─────────────────────────────────────────────────────────────
def load_png(path):
    """Return (2D float array, maxval, info) for a grayscale PNG."""
    img = Image.open(path)
    info = {"reader": "PIL", "mode": img.mode, "size": list(img.size)}
    if img.mode == "L":
        arr, maxval = np.array(img, dtype=np.float64), 255.0
    elif img.mode in ("I;16", "I;16B", "I"):
        arr, maxval = np.array(img, dtype=np.float64), 65535.0
    else:
        info["converted"] = f"{img.mode} -> L"
        arr, maxval = np.array(img.convert("L"), dtype=np.float64), 255.0
    info["steps"] = [f"grayscale PNG read ({img.mode}), maxval={maxval:g}"]
    return arr, maxval, info


def load_dicom(path):
    """Return (2D float array in [0, maxval], maxval, info) for a radiograph DICOM.

    Applies Modality LUT / rescale and VOI LUT / windowing when present, and
    inverts MONOCHROME1 so that higher values are brighter (MONOCHROME2).
    """
    ds = pydicom.dcmread(path)
    photometric = str(ds.get("PhotometricInterpretation", ""))
    info = {
        "reader": f"pydicom {pydicom.__version__}",
        "transfer_syntax": ds.file_meta.TransferSyntaxUID.name,
        "modality": str(ds.get("Modality", "")),
        "body_part": str(ds.get("BodyPartExamined", "")),
        "view_position": str(ds.get("ViewPosition", "")),
        "photometric": photometric,
        "rows": int(ds.Rows), "columns": int(ds.Columns),
        "bits_stored": int(ds.BitsStored), "samples_per_pixel": int(ds.get("SamplesPerPixel", 1)),
        "steps": [],
    }
    if info["samples_per_pixel"] != 1:
        raise ValueError(f"Expected single-channel radiograph, got SamplesPerPixel={info['samples_per_pixel']}")
    arr = ds.pixel_array.astype(np.float64)
    info["steps"].append(f"pixel_array decoded {arr.shape} range [{arr.min():g}, {arr.max():g}]")
    maxval = float(2 ** info["bits_stored"] - 1)
    lut_applied = False
    if "ModalityLUTSequence" in ds or "RescaleSlope" in ds or "RescaleIntercept" in ds:
        arr = apply_modality_lut(arr, ds).astype(np.float64)
        info["steps"].append("Modality LUT / rescale applied")
        lut_applied = True
    else:
        info["steps"].append("no Modality LUT / rescale present")
    if "VOILUTSequence" in ds or "WindowCenter" in ds:
        arr = apply_voi_lut(arr, ds).astype(np.float64)
        info["steps"].append("VOI LUT / windowing applied")
        lut_applied = True
    else:
        info["steps"].append("no VOI LUT / window present")
    if lut_applied:
        lo, hi = arr.min(), arr.max()
        arr = (arr - lo) / (hi - lo) * 255.0 if hi > lo else np.zeros_like(arr)
        maxval = 255.0
        info["steps"].append("min-max rescaled to [0, 255] after LUT")
    if photometric == "MONOCHROME1":
        arr = maxval - arr
        info["steps"].append("MONOCHROME1 inverted to MONOCHROME2 polarity")
    elif photometric == "MONOCHROME2":
        info["steps"].append("MONOCHROME2: no inversion")
    else:
        raise ValueError(f"Unsupported PhotometricInterpretation for a radiograph: {photometric!r}")
    info["steps"].append(f"maxval={maxval:g} (BitsStored={info['bits_stored']})")
    return arr, maxval, info


def load_case(kind, path):
    return load_png(path) if kind == "png" else load_dicom(path)


# ── Preprocessing ─────────────────────────────────────────────────────────
def preprocess(arr, maxval):
    """TorchXRayVision scaling → XRayCenterCrop → bilinear resize to 224.

    Returns (tensor [1,1,224,224] on CPU, crop box (y0, x0, size)).
    """
    norm = xrv.utils.normalize(arr, maxval)            # [-1024, 1024]
    chw = norm[None, :, :]
    _, h, w = chw.shape
    size = min(h, w)
    y0, x0 = h // 2 - size // 2, w // 2 - size // 2
    cropped = xrv.datasets.XRayCenterCrop()(chw)       # square on the short side
    t = torch.from_numpy(np.ascontiguousarray(cropped[None])).float()
    t = F.interpolate(t, size=(INPUT_SIZE, INPUT_SIZE), mode="bilinear", align_corners=False)
    return t, (y0, x0, size)


# ── Grad-CAM (same math as validate_model.py) ─────────────────────────────
def grad_cam(model, x, target_idx, layer):
    activations, gradients = [], []
    h1 = layer.register_forward_hook(lambda _m, _i, out: activations.append(out))
    h2 = layer.register_full_backward_hook(lambda _m, _gi, gout: gradients.append(gout[0]))
    try:
        xin = x.detach().clone().requires_grad_(True)
        model.zero_grad(set_to_none=True)
        out = model(xin)
        out[0, target_idx].backward()
    finally:
        h1.remove()
        h2.remove()
    act, grad = activations[0].detach(), gradients[0].detach()
    alpha = torch.mean(grad, dim=(2, 3), keepdim=True)
    cam = F.relu(torch.sum(alpha * act, dim=1, keepdim=True))
    cam = F.interpolate(cam, size=x.shape[-2:], mode="bilinear", align_corners=False)
    cam_np = cam[0, 0].cpu().numpy()
    lo, hi = float(cam_np.min()), float(cam_np.max())
    cam_norm = (cam_np - lo) / (hi - lo) if hi > lo else np.zeros_like(cam_np)
    meta = {
        "target_score_in_grad_pass": float(out[0, target_idx].item()),
        "activation_shape": list(act.shape),
        "gradient_shape": list(grad.shape),
        "gradient_norm": float(grad.norm().item()),
        "cam_raw_min": lo, "cam_raw_max": hi,
    }
    return cam_norm.astype(np.float32), meta


# ── Artifacts ─────────────────────────────────────────────────────────────
def to_uint8(arr, lo=None, hi=None):
    lo = arr.min() if lo is None else lo
    hi = arr.max() if hi is None else hi
    return (np.clip((arr - lo) / (hi - lo) if hi > lo else arr * 0, 0, 1) * 255).round().astype(np.uint8)


def overlay_on_original(orig_u8, crop, cam_norm):
    """Blend the heatmap onto the center-cropped region of the original radiograph."""
    y0, x0, size = crop
    region = orig_u8[y0:y0 + size, x0:x0 + size]
    cam_full = np.array(Image.fromarray(cam_norm).resize((size, size), Image.BILINEAR))
    heat = apply_jet_colormap(cam_full)
    base = np.stack([region] * 3, axis=-1).astype(np.float32)
    return (0.55 * base + 0.45 * heat).astype(np.uint8), heat


def _font(size, bold=False):
    for name in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def write_composite(path, orig_u8, heat_224, overlay, summary):
    panel, pad, top, title_h = 512, 20, 70, 30
    lines = [
        f"Case: {summary['case']}",
        f"Grad-CAM target: {summary['target']}    Model score: {summary['score']:.4f} "
        "(threshold-rescaled model score; not calibrated diagnostic probability)",
        f"Model: TorchXRayVision DenseNet-121    Weights: {WEIGHTS_ID}    Target layer: {GRADCAM_LAYER}",
        f"Inference device: {summary['device']}    Inference (median): {summary['infer_ms']:.2f} ms    "
        f"Grad-CAM (median): {summary['cam_ms']:.2f} ms    End-to-end single pass: {summary['e2e_ms']:.2f} ms",
        f"Validation status: {summary['status']}",
        "The heatmap shows image regions that influenced this model output. It is not evidence of disease.",
    ]
    text_h = 28 * len(lines) + pad
    width = 3 * panel + 4 * pad
    canvas = Image.new("RGB", (width, top + title_h + panel + pad + text_h), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, width, top - 10], fill="#b00020")
    draw.text((pad, 14), BANNER, fill="white", font=_font(30, bold=True))
    panels = [(Image.fromarray(orig_u8).convert("RGB"), "Original radiograph"),
              (Image.fromarray(heat_224), f"Grad-CAM heatmap ({INPUT_SIZE}x{INPUT_SIZE} model space)"),
              (Image.fromarray(overlay), "Grad-CAM overlay on original (center crop)")]
    for i, (img, title) in enumerate(panels):
        x0 = pad + i * (panel + pad)
        draw.text((x0, top), title, fill="black", font=_font(18, bold=True))
        img = img.resize((panel, panel), Image.BILINEAR)  # display scaling only
        canvas.paste(img, (x0, top + title_h))
    y = top + title_h + panel + pad
    for line in lines:
        draw.text((pad, y), line, fill="black", font=_font(18))
        y += 28
    canvas.save(path)


# ── Ground truth (from dataset files bundled with torchxrayvision) ────────
def dataset_annotation(case):
    if case["key"] == "nih_png":
        df = pd.read_csv(os.path.join(XRV_DATA, "Data_Entry_2017_v2020.csv.gz"))
        row = df[df["Image Index"] == case["image_file"]]
        if row.empty:
            return {"available": False}
        r = row.iloc[0]
        return {
            "available": True,
            "source_file": "torchxrayvision/data/Data_Entry_2017_v2020.csv.gz",
            "finding_labels": str(r["Finding Labels"]).split("|"),
            "view_position": str(r["View Position"]),
            "original_size": [int(r["OriginalImage[Width"]), int(r["Height]"])],
            "related_model_outputs": [p for p in str(r["Finding Labels"]).split("|")
                                      if p in EXPECTED_PATHOLOGIES],
            "caveat": "NIH ChestX-ray14 labels were derived from radiology reports by NLP/text "
                      "mining; they are not radiologist-confirmed per-image ground truth.",
        }
    df = pd.read_csv(os.path.join(XRV_DATA, "siim-pneumothorax-train-rle.csv.gz"))
    uid = case["image_file"][:-4]
    rows = df[df["ImageId"] == uid]
    if rows.empty:
        return {"available": False}
    masks = [str(v).strip() for v in rows.iloc[:, 1]]
    positive = any(m != "-1" for m in masks)
    return {
        "available": True,
        "source_file": "torchxrayvision/data/siim-pneumothorax-train-rle.csv.gz",
        "finding_labels": ["Pneumothorax (mask annotated)" if positive
                           else "no pneumothorax (EncodedPixels = -1)"],
        "encoded_pixels": masks,
        "related_model_outputs": ["Pneumothorax"],
        "caveat": "SIIM-ACR annotates pneumothorax only; this says nothing about other findings.",
    }


def annotation_statement(ann, scores):
    if not ann.get("available"):
        return ("No ground-truth label was available for this validation image; therefore this case "
                "is suitable for pipeline/inference validation but not accuracy validation.")
    parts = [f"{p} score = {scores[p]:.4f}" for p in ann["related_model_outputs"]]
    return (f"The dataset annotation for this image indicates {', '.join(ann['finding_labels'])}"
            + (f", while the model produced: {'; '.join(parts)}." if parts
               else "; no model output corresponds directly to this annotation.")
            + " A single image cannot establish accuracy.")


# ── Main ──────────────────────────────────────────────────────────────────
def run_case(case, model, device, checks):
    key, prefix = case["key"], CASE_PREFIX[case["key"]]
    src = os.path.join(OUT, case["local_file"])
    kind = "png" if src.lower().endswith(".png") else "dicom"
    case["image_file"] = os.path.basename(src)
    print(f"\n{'=' * 70}\nCASE: {key} ({case['role']})\n{'=' * 70}")
    result = {"key": key, "role": case["role"], "source_file": case["local_file"],
              "dataset": case["dataset"], "format": kind}

    sha_before = sha256_file(src)
    checks.add(f"{key}: source SHA-256 matches provenance (before)",
               sha_before == case["sha256"], sha_before)
    ro = not os.access(src, os.W_OK)
    checks.add(f"{key}: original stored read-only", ro)

    # Ingestion
    print("\n-- INGESTION --")
    try:
        arr, maxval, ing = load_case(kind, src)
    except Exception as exc:  # decoding failure is reported, not hidden
        checks.add(f"{key}: decode", False, f"{type(exc).__name__}: {exc}")
        result["decode_error"] = f"{type(exc).__name__}: {exc}"
        return result
    for s in ing["steps"]:
        print(f"  {s}")
    result["ingestion"] = ing
    checks.add(f"{key}: decoded 2D grayscale", arr.ndim == 2, f"shape={arr.shape}")
    checks.add(f"{key}: pixel range within [0, maxval]",
               arr.min() >= 0 and arr.max() <= maxval, f"[{arr.min():g}, {arr.max():g}] maxval={maxval:g}")

    # Preprocessing
    print("\n-- PREPROCESSING --")
    x_cpu, crop = preprocess(arr, maxval)
    print(f"  crop (y0, x0, size) = {crop}  tensor={list(x_cpu.shape)}  "
          f"range=[{x_cpu.min():.1f}, {x_cpu.max():.1f}] mean={x_cpu.mean():.1f}")
    result["preprocessing"] = {
        "path": [
            *ing["steps"],
            f"xrv.utils.normalize(img, maxval={maxval:g}) -> [-1024, 1024]",
            f"xrv.datasets.XRayCenterCrop -> {crop[2]}x{crop[2]} (y0={crop[0]}, x0={crop[1]})",
            "torch.nn.functional.interpolate(bilinear, align_corners=False) -> 224x224",
            "tensor [1, 1, 224, 224] float32",
        ],
        "tensor_shape": list(x_cpu.shape),
        "tensor_min": float(x_cpu.min()), "tensor_max": float(x_cpu.max()),
        "tensor_mean": float(x_cpu.mean()), "tensor_std": float(x_cpu.std()),
    }
    checks.add(f"{key}: 224x224 tensor", list(x_cpu.shape) == [1, 1, INPUT_SIZE, INPUT_SIZE], list(x_cpu.shape))
    checks.add(f"{key}: tensor has no NaN/Inf", bool(torch.isfinite(x_cpu).all()))
    checks.add(f"{key}: tensor within xrv range [-1024, 1024]",
               x_cpu.min() >= -1024.001 and x_cpu.max() <= 1024.001)

    # CPU-side timing (ingestion + preprocessing)
    ing_ms, pre_ms = [], []
    for _ in range(N_CPU):
        t0 = time.perf_counter()
        a2, m2, _ = load_case(kind, src)
        t1 = time.perf_counter()
        preprocess(a2, m2)
        t2 = time.perf_counter()
        ing_ms.append((t1 - t0) * 1000)
        pre_ms.append((t2 - t1) * 1000)

    x = x_cpu.to(device)
    layer = model.features.denseblock4

    # Cold first call, then warm-up
    cuda_sync(device)
    t0 = time.perf_counter()
    with torch.no_grad():
        model(x)
    cuda_sync(device)
    cold_ms = (time.perf_counter() - t0) * 1000
    with torch.no_grad():
        for _ in range(WARMUP):
            model(x)
    for _ in range(3):
        grad_cam(model, x, 0, layer)
    cuda_sync(device)

    # Inference timing + memory
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
        mem_base = torch.cuda.memory_allocated(device)
    inf_ms = []
    for _ in range(N_INFER):
        cuda_sync(device)
        t0 = time.perf_counter()
        with torch.no_grad():
            out = model(x)
        cuda_sync(device)
        inf_ms.append((time.perf_counter() - t0) * 1000)
    mem = {}
    if device.type == "cuda":
        mem["baseline_allocated_mb"] = round(mem_base / 1024 ** 2, 2)
        mem["inference_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated(device) / 1024 ** 2, 2)

    scores_t = out[0].detach().cpu()
    scores = {p: float(v) for p, v in zip(model.pathologies, scores_t.numpy())}
    print("\n-- ALL 18 MODEL SCORES (threshold-rescaled; not calibrated diagnostic probability) --")
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    for r, (p, v) in enumerate(ranked, 1):
        print(f"  {r:2d}. {p:28s} {v:.4f}")
    checks.add(f"{key}: 18 outputs", scores_t.numel() == 18, scores_t.numel())
    checks.add(f"{key}: scores finite", bool(torch.isfinite(scores_t).all()))
    checks.add(f"{key}: scores in [0, 1]", bool(((scores_t >= 0) & (scores_t <= 1)).all()),
               f"[{scores_t.min():.4f}, {scores_t.max():.4f}]")

    # Target selection: highest-scoring output that is a real, valid model output
    valid = [i for i, p in enumerate(model.pathologies)
             if p and not torch.isnan(model.op_threshs[i]).item()]
    target_idx = max(valid, key=lambda i: scores_t[i].item())
    target = model.pathologies[target_idx]
    low_idx = min(valid, key=lambda i: scores_t[i].item())
    print(f"\n  Grad-CAM target: {target} (index {target_idx}, model score {scores[target]:.4f})")
    checks.add(f"{key}: target is a real model output",
               target in EXPECTED_PATHOLOGIES and target_idx in valid, f"{target} [{target_idx}]")

    # Grad-CAM timing + memory
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    cam_ms = []
    for _ in range(N_CAM):
        cuda_sync(device)
        t0 = time.perf_counter()
        cam, cam_meta = grad_cam(model, x, target_idx, layer)
        cuda_sync(device)
        cam_ms.append((time.perf_counter() - t0) * 1000)
    if device.type == "cuda":
        mem["gradcam_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated(device) / 1024 ** 2, 2)
        mem["peak_reserved_mb"] = round(torch.cuda.max_memory_reserved(device) / 1024 ** 2, 2)

    print("\n-- GRAD-CAM --")
    print(f"  Grad-CAM target: {target}\n  Target layer   : {GRADCAM_LAYER}")
    for k, v in cam_meta.items():
        print(f"  {k}: {v}")
    active = float((cam > 0.2).mean())
    checks.add(f"{key}: heatmap {INPUT_SIZE}x{INPUT_SIZE}", cam.shape == (INPUT_SIZE, INPUT_SIZE), cam.shape)
    checks.add(f"{key}: heatmap finite", bool(np.isfinite(cam).all()))
    checks.add(f"{key}: non-zero gradient", cam_meta["gradient_norm"] > 0, f"{cam_meta['gradient_norm']:.6g}")
    checks.add(f"{key}: non-trivial activation", cam_meta["cam_raw_max"] > 0 and 0.01 < active < 0.99,
               f"raw max={cam_meta['cam_raw_max']:.6g}, {active * 100:.1f}% of pixels > 0.2")
    checks.add(f"{key}: grad pass score equals inference score",
               abs(cam_meta["target_score_in_grad_pass"] - scores[target]) < 1e-4)
    cam_low, _ = grad_cam(model, x, low_idx, layer)
    corr = float(np.corrcoef(cam.ravel(), cam_low.ravel())[0, 1])
    checks.add(f"{key}: heatmap is class-specific (differs from lowest-scoring target)",
               corr < 0.99, f"corr vs {model.pathologies[low_idx]} CAM = {corr:.3f}")

    # End-to-end single pass (after warm-up; excludes model load and file writes)
    cuda_sync(device)
    t0 = time.perf_counter()
    a3, m3, _ = load_case(kind, src)
    x3, _ = preprocess(a3, m3)
    x3 = x3.to(device)
    with torch.no_grad():
        o3 = model(x3)
    ti = int(torch.argmax(o3[0]).item())
    grad_cam(model, x3, ti, layer)
    cuda_sync(device)
    e2e_ms = (time.perf_counter() - t0) * 1000

    timing = {
        "ingestion": stats(ing_ms), "preprocessing": stats(pre_ms),
        "inference_cold_first_call_ms": round(cold_ms, 3),
        "inference": stats(inf_ms), "gradcam": stats(cam_ms),
        "end_to_end_single_pass_ms": round(e2e_ms, 3),
        "notes": f"{WARMUP} warm-up inferences + 3 warm-up Grad-CAM passes; CUDA synchronized "
                 "before and after each timed section. End-to-end = decode + preprocess + H2D + "
                 "inference + Grad-CAM (no model load, no file I/O for artifacts).",
    }
    print("\n-- TIMING (measured) --")
    for k in ("ingestion", "preprocessing", "inference", "gradcam"):
        print(f"  {k:14s} median={timing[k]['median_ms']:.3f} ms  p95={timing[k]['p95_ms']:.3f} ms")
    print(f"  cold first inference = {cold_ms:.2f} ms   end-to-end = {e2e_ms:.2f} ms")
    print(f"  GPU memory: {mem}")
    checks.add(f"{key}: runtime measured", all(v > 0 for v in (np.median(inf_ms), np.median(cam_ms), e2e_ms)))
    if device.type == "cuda":
        checks.add(f"{key}: GPU memory measured", mem["inference_peak_allocated_mb"] > 0)

    # Ground truth (kept separate from model output)
    ann = dataset_annotation(case)
    statement = annotation_statement(ann, scores)
    print(f"\n-- DATASET ANNOTATION --\n  {statement}")
    checks.add(f"{key}: ground truth handled from dataset file", "available" in ann)

    # Artifacts
    print("\n-- ARTIFACTS --")
    orig_u8 = to_uint8(arr, 0, maxval)
    names = {
        "original": f"{prefix}original_real_cxr.png",
        "preprocessed": f"{prefix}real_cxr_preprocessed.png",
        "heatmap": f"{prefix}real_cxr_gradcam_heatmap.png",
        "overlay": f"{prefix}real_cxr_gradcam_overlay.png",
        "composite": f"{prefix}real_cxr_validation_composite.png",
        "scores": f"{prefix}real_cxr_scores.json",
    }
    Image.fromarray(orig_u8).save(os.path.join(OUT, names["original"]))
    Image.fromarray(to_uint8(x_cpu[0, 0].numpy(), -1024, 1024)).save(os.path.join(OUT, names["preprocessed"]))
    heat_224 = apply_jet_colormap(cam)
    Image.fromarray(heat_224).save(os.path.join(OUT, names["heatmap"]))
    overlay, _ = overlay_on_original(orig_u8, crop, cam)
    Image.fromarray(overlay).save(os.path.join(OUT, names["overlay"]))

    if kind == "png":
        same = np.array_equal(np.array(Image.open(os.path.join(OUT, names["original"]))),
                              np.array(Image.open(src)))
        checks.add(f"{key}: original_real_cxr.png is pixel-identical to source", same)
    checks.add(f"{key}: overlay generated", overlay.shape == (crop[2], crop[2], 3), overlay.shape)

    with open(os.path.join(OUT, names["scores"]), "w", encoding="utf-8") as f:
        json.dump({"case": key, "weights": WEIGHTS_ID,
                   "score_semantics": "TorchXRayVision output: sigmoid followed by op_norm "
                                      "(0.5 = model operating threshold). Not calibrated diagnostic probability.",
                   "scores": scores, "ranked": [p for p, _ in ranked]}, f, indent=2)

    case_ok = all(i["pass"] for i in checks.items if i["check"].startswith(f"{key}:"))
    summary = {"case": f"{key} — {case['dataset']}", "target": target, "score": scores[target],
               "device": torch.cuda.get_device_name(device) if device.type == "cuda" else platform.processor(),
               "infer_ms": timing["inference"]["median_ms"], "cam_ms": timing["gradcam"]["median_ms"],
               "e2e_ms": e2e_ms, "status": "PIPELINE CHECKS PASSED" if case_ok else "PIPELINE CHECKS FAILED"}
    write_composite(os.path.join(OUT, names["composite"]), orig_u8, heat_224, overlay, summary)

    for n in names.values():
        p = os.path.join(OUT, n)
        checks.add(f"{key}: artifact {n}", os.path.getsize(p) > 0, f"{os.path.getsize(p) / 1024:.1f} KB")

    sha_after = sha256_file(src)
    checks.add(f"{key}: source SHA-256 unchanged (after)", sha_after == sha_before, sha_after)

    result.update({
        "scores": scores, "ranked": [p for p, _ in ranked],
        "gradcam": {"target": target, "target_index": target_idx, "target_score": scores[target],
                    "selection": "highest-scoring valid model output",
                    "layer": GRADCAM_LAYER, **cam_meta,
                    "fraction_pixels_above_0.2": active,
                    "contrast_target": model.pathologies[low_idx],
                    "corr_with_contrast_target_cam": corr},
        "timing": timing, "gpu_memory": mem,
        "dataset_annotation": ann, "annotation_statement": statement,
        "artifacts": {k: f"backend/tests/artifacts/real_cxr/{v}" for k, v in names.items()},
        "source_sha256_before": sha_before, "source_sha256_after": sha_after,
    })
    return result


def main():
    warnings.simplefilter("always")
    print("=" * 70)
    print("HOLOMED CHEST X-RAY AI  |  PHASE 2 REAL CXR VALIDATION")
    print(BANNER)
    print("=" * 70)
    checks = Checks()

    with open(PROVENANCE, encoding="utf-8") as f:
        provenance = json.load(f)
    checks.add("provenance.json present", len(provenance.get("cases", [])) >= 1)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    system = {
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu": platform.processor(), "torch": torch.__version__,
        "torchxrayvision": xrv.__version__, "pydicom": pydicom.__version__,
        "cuda_available": torch.cuda.is_available(), "device": str(device),
        "cuda_runtime": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
    }
    if device.type == "cuda":
        system["gpu"] = torch.cuda.get_device_name(device)
        system["gpu_total_memory_gb"] = round(torch.cuda.get_device_properties(device).total_memory / 1024 ** 3, 2)
    print("\n-- SYSTEM --")
    for k, v in system.items():
        print(f"  {k}: {v}")

    print("\n-- MODEL --")
    local_sha = sha256_file(WEIGHTS)
    checks.add("local weights SHA-256 matches validated value", local_sha == EXPECTED_WEIGHTS_SHA256, local_sha)
    t0 = time.perf_counter()
    model = xrv.models.DenseNet(weights=WEIGHTS_ID)
    model.to(device).eval()
    cuda_sync(device)
    load_ms = (time.perf_counter() - t0) * 1000
    loaded_path = model.weights_filename_local
    loaded_sha = sha256_file(loaded_path)
    checks.add("weights file loaded by xrv is byte-identical to local weights", loaded_sha == local_sha, loaded_path)
    checks.add("architecture is TorchXRayVision DenseNet-121",
               isinstance(model, xrv.models.DenseNet)
               and [len(getattr(model.features, f"denseblock{i}")) for i in range(1, 5)] == [6, 12, 24, 16]
               and model.classifier.in_features == 1024 and model.classifier.out_features == 18)
    checks.add("18 model targets match expected list", list(model.pathologies) == EXPECTED_PATHOLOGIES)
    checks.add("op_threshs present (output = sigmoid + op_norm)",
               model.op_threshs is not None and not torch.isnan(model.op_threshs).any())
    checks.add("model on expected device", next(model.parameters()).device.type == device.type, device)
    n_params = sum(p.numel() for p in model.parameters())
    model_info = {
        "architecture": "TorchXRayVision DenseNet-121 (densenet121, growth 32, blocks 6/12/24/16, 1 input channel)",
        "weights": WEIGHTS_ID, "local_weights": WEIGHTS, "local_sha256": local_sha,
        "xrv_loaded_file": loaded_path, "xrv_loaded_sha256": loaded_sha,
        "weights_url": xrv.models.model_urls[WEIGHTS_ID]["weights_url"],
        "parameters": n_params, "targets": list(model.pathologies),
        "op_threshs": [float(v) for v in model.op_threshs.cpu()],
        "load_ms": round(load_ms, 3),
    }
    print(f"  weights url : {model_info['weights_url']}")
    print(f"  loaded file : {loaded_path}\n  sha256      : {loaded_sha}\n  params      : {n_params}")
    print(f"  load time   : {load_ms:.1f} ms")

    results = []
    for case in provenance["cases"]:
        results.append(run_case(case, model, device, checks))

    primary_ok = any(r["key"] == "nih_png" and "scores" in r for r in results)
    checks.add("primary real CXR (NIH PNG) validated", primary_ok)

    status = "PASS" if checks.passed else "FAIL"
    report = {
        "phase": "Phase 2 — Real Chest X-Ray Validation",
        "banner": BANNER, "status": status,
        "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system": system, "model": model_info, "cases": results, "checks": checks.items,
        "scope": "Software/model execution validation only. No clinical performance, "
                 "diagnostic accuracy, safety, or regulatory claim is made.",
    }
    with open(os.path.join(OUT, "validation_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    n_pass = sum(i["pass"] for i in checks.items)
    print("\n" + "=" * 70)
    print(f"PHASE 2 STATUS: {status}  ({n_pass}/{len(checks.items)} checks passed)")
    print("=" * 70)
    return 0 if checks.passed else 1


if __name__ == "__main__":
    sys.exit(main())
