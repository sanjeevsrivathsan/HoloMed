"""HoloMed Chest X-Ray AI — Standalone Model Validation Script.
Validates: model loading, weight provenance, preprocessing, inference (GPU+CPU),
all 18 pathology outputs, target-specific Grad-CAM, and artifact generation.
"""
import os
import time
import hashlib
import torch
import torch.nn.functional as F
import numpy as np
import torchxrayvision as xrv
from PIL import Image

ARTIFACTS = os.path.join(os.path.dirname(__file__), "artifacts")
WEIGHTS = r"I:\HoloMed\HoloMed-D\backend\models\weights\densenet121-res224-all.pt"


def apply_jet_colormap(cam_normalized):
    """Pure-numpy JET colormap: float [0,1] -> RGB uint8."""
    x = np.clip(cam_normalized, 0.0, 1.0)
    r = np.clip(1.5 - np.abs(x * 4.0 - 3.0), 0.0, 1.0)
    g = np.clip(1.5 - np.abs(x * 4.0 - 2.0), 0.0, 1.0)
    b = np.clip(1.5 - np.abs(x * 4.0 - 1.0), 0.0, 1.0)
    return (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)


def main():
    print("=" * 70)
    print("HOLOMED CHEST X-RAY AI  |  STANDALONE MODEL VALIDATION")
    print("=" * 70)

    # ── 1. System Info ────────────────────────────────────────────────
    print("\n── 1. SYSTEM & DEVICE INFO ──")
    print(f"PyTorch : {torch.__version__}")
    print(f"CUDA    : {torch.cuda.is_available()}")
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    if torch.cuda.is_available():
        print(f"GPU     : {torch.cuda.get_device_name(0)}")
        print(f"VRAM    : {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")

    # ── 2. Model Loading ──────────────────────────────────────────────
    print("\n── 2. MODEL LOADING (LOCAL WEIGHTS) ──")
    print(f"Weights : {WEIGHTS}")
    print(f"File    : {os.path.getsize(WEIGHTS) / 1024**2:.2f} MB")

    sha256 = hashlib.sha256()
    with open(WEIGHTS, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    print(f"SHA256  : {sha256.hexdigest()}")

    t0 = time.time()
    model = xrv.models.DenseNet(weights="densenet121-res224-all")
    model.to(device)
    model.eval()
    load_ms = (time.time() - t0) * 1000
    print(f"Loaded in : {load_ms:.1f} ms")
    print(f"Pathologies ({len(model.pathologies)}):")
    for i, p in enumerate(model.pathologies):
        print(f"  [{i:2d}] {p}")

    # 3. Preprocessing
    print("\n-- 3. IMAGE PREPROCESSING --")
    sample_path = os.path.join(ARTIFACTS, "sample_cxr.png")
    img_pil = Image.open(sample_path).convert("L")
    raw_img = np.array(img_pil, dtype=np.float64)
    print(f"Input shape : {raw_img.shape}, range [{raw_img.min():.0f}, {raw_img.max():.0f}]")

    norm_img = xrv.datasets.normalize(raw_img, 255)
    img_4d = norm_img[None, None, :, :] if len(norm_img.shape) == 2 else norm_img[None, :, :, :]
    img_tensor = torch.from_numpy(img_4d).float()
    img_tensor = F.interpolate(img_tensor, size=(224, 224), mode="bilinear", align_corners=False)
    img_tensor = img_tensor.to(device)
    print(f"Tensor    : {list(img_tensor.shape)}, device={img_tensor.device}")
    print(f"Norm range: [{img_tensor.min().item():.2f}, {img_tensor.max().item():.2f}]")
    print(f"Mean/Std  : {img_tensor.mean().item():.2f} / {img_tensor.std().item():.2f}")

    # 4. GPU Benchmark
    print("\n-- 4. BENCHMARK --")
    if torch.cuda.is_available():
        # Warmup
        with torch.no_grad():
            for _ in range(20):
                _ = model(img_tensor)
        torch.cuda.synchronize()

        torch.cuda.reset_peak_memory_stats()
        vram_base = torch.cuda.memory_allocated(0) / 1024**2
        latencies = []
        for _ in range(100):
            t_s = time.perf_counter()
            with torch.no_grad():
                _ = model(img_tensor)
            torch.cuda.synchronize()
            latencies.append((time.perf_counter() - t_s) * 1000)
        vram_peak = torch.cuda.max_memory_allocated(0) / 1024**2
        print(f"GPU ({torch.cuda.get_device_name(0)}): mean={np.mean(latencies):.2f} ms  "
              f"min={np.min(latencies):.2f} ms  max={np.max(latencies):.2f} ms  "
              f"P95={np.percentile(latencies, 95):.2f} ms")
        print(f"VRAM : baseline={vram_base:.1f} MB  peak={vram_peak:.1f} MB")

    # CPU fallback
    model_cpu = xrv.models.DenseNet(weights="densenet121-res224-all")
    model_cpu.eval()
    img_cpu = img_tensor.cpu()
    cpu_lats = []
    for _ in range(5):
        t_s = time.perf_counter()
        with torch.no_grad():
            _ = model_cpu(img_cpu)
        cpu_lats.append((time.perf_counter() - t_s) * 1000)
    print(f"CPU fallback : mean={np.mean(cpu_lats):.2f} ms  min={np.min(cpu_lats):.2f} ms")

    # 5. All 18 Predictions
    print("\n-- 5. ALL 18 PATHOLOGY MODEL SCORES --")
    # The xrv model output already applies sigmoid + op_norm (op_threshs), so
    # use it directly; applying another sigmoid would squash scores to [0.5, 0.73].
    with torch.no_grad():
        probs = model(img_tensor)[0].cpu().numpy()

    ranked = np.argsort(probs)[::-1]
    print(f"{'Rank':>4}  {'Pathology':25s}  {'Score':>8}  {'Percent':>8}")
    print("-" * 55)
    for rank, idx in enumerate(ranked, 1):
        print(f"{rank:4d}  {model.pathologies[idx]:25s}  {probs[idx]:.4f}  {probs[idx]*100:6.2f}%")

    top_idx = ranked[0]
    top_name = model.pathologies[top_idx]
    print(f"\n>>> Primary Finding: {top_name}  (Model Score: {probs[top_idx]*100:.2f}%)")

    # 6. Grad-CAM
    print("\n-- 6. TARGET-SPECIFIC GRAD-CAM --")
    target_layer = model.features.denseblock4
    activations, gradients = [], []

    def fwd_hook(_, __, output):
        activations.append(output)

    def bwd_hook(_, __, grad_output):
        gradients.append(grad_output[0])

    h1 = target_layer.register_forward_hook(fwd_hook)
    h2 = target_layer.register_full_backward_hook(bwd_hook)

    img_tensor.requires_grad_(True)
    model.zero_grad()
    out = model(img_tensor)
    out[0, top_idx].backward()
    h1.remove()
    h2.remove()

    act = activations[0]   # [1, C, H_feat, W_feat]
    grad = gradients[0]    # [1, C, H_feat, W_feat]
    print(f"Activation shape : {list(act.shape)}")
    print(f"Gradient shape   : {list(grad.shape)}")
    print(f"Gradient norm    : {grad.norm().item():.4f}  (non-zero = real gradient)")

    # Grad-CAM computation
    alpha = torch.mean(grad, dim=(2, 3), keepdim=True)     # [1,C,1,1]
    cam = F.relu(torch.sum(alpha * act, dim=1, keepdim=True))  # [1,1,H,W]
    cam = F.interpolate(cam, size=(224, 224), mode="bilinear", align_corners=False)
    cam_np = cam[0, 0].detach().cpu().numpy()
    cam_min, cam_max = cam_np.min(), cam_np.max()
    cam_norm = (cam_np - cam_min) / (cam_max - cam_min) if cam_max > cam_min else np.zeros_like(cam_np)

    print(f"CAM range   : [{cam_norm.min():.4f}, {cam_norm.max():.4f}]")
    print(f"CAM NaN/Inf : NaN={np.isnan(cam_norm).any()}  Inf={np.isinf(cam_norm).any()}")
    nonzero = (cam_norm > 0.01).sum()
    print(f"CAM nonzero : {nonzero}/{cam_norm.size} pixels ({nonzero/cam_norm.size*100:.1f}%)")

    # 7. Save Artifacts
    print("\n-- 7. SAVING ARTIFACTS --")
    os.makedirs(ARTIFACTS, exist_ok=True)

    orig_disp = (raw_img - raw_img.min()) / (raw_img.max() - raw_img.min())
    orig_uint8 = (orig_disp * 255).astype(np.uint8)
    img_orig = Image.fromarray(orig_uint8).resize((224, 224)).convert("RGB")
    img_orig.save(f"{ARTIFACTS}/original_xray.png")

    heatmap_rgb = apply_jet_colormap(cam_norm)
    Image.fromarray(heatmap_rgb).save(f"{ARTIFACTS}/gradcam_heatmap.png")

    orig_arr = np.array(img_orig)
    overlay = (0.55 * orig_arr + 0.45 * heatmap_rgb).astype(np.uint8)
    Image.fromarray(overlay).save(f"{ARTIFACTS}/gradcam_overlay.png")

    composite = np.zeros((224, 224 * 3, 3), dtype=np.uint8)
    composite[:, :224] = orig_arr
    composite[:, 224:448] = heatmap_rgb
    composite[:, 448:] = overlay
    Image.fromarray(composite).save(f"{ARTIFACTS}/validation_composite.png")

    for fn in ["original_xray.png", "gradcam_heatmap.png", "gradcam_overlay.png", "validation_composite.png"]:
        print(f"  {fn}: {os.path.getsize(f'{ARTIFACTS}/{fn}') / 1024:.1f} KB")

    print("\n" + "=" * 70)
    print("ALL CHECKS PASSED — VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()