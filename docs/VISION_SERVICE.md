# Vision AI Service (Phase 3)

> **The model has not been clinically validated by HoloMed.**
> The service provides AI-generated screening assistance. Its outputs are model
> scores and visual explanations that require clinical review. They are not
> diagnostic determinations.

This service wraps the chest radiograph pipeline validated in Phase 1 and Phase 2
(`docs/REAL_CXR_VALIDATION.md`) in a reusable backend component and one API
endpoint. The frontend is not integrated yet.

## 1. Architecture

```
backend/
  config.py                     VISION_* settings (env-overridable)
  routers/vision.py             POST /api/v1/vision/screen
  services/vision/
    __init__.py                 no heavy imports
    schemas.py                  pydantic response models, safety text (no torch import)
    model.py                    checkpoint verification, loading, singleton, device, lock
    preprocessing.py            PNG/JPEG/DICOM decode -> [1,1,224,224] tensor
    inference.py                orchestration: preprocess -> scores -> Grad-CAM -> response
    explainability.py           Grad-CAM (features.denseblock4), JET colormap, PNG rendering
    provider.py                 VisionProvider selection (VISION_PROVIDER), optional preload
  tests/test_vision_service.py  service + API tests
  tests/benchmark_vision_service.py  baseline benchmark
frontend/src/
  lib/vision.ts                          typed client, upload validation, error mapping
  components/vision/ChestXrayScreening.tsx  Imaging → "AI Screening" workspace (Phase 4)
```

### Provider layer (deployment readiness)

```
routers/vision.py → provider.get_vision_provider() → VisionProvider.screen(bytes, target)
                                                     ├── LocalVisionProvider  (VISION_PROVIDER=local, default)
                                                     └── CloudVisionProvider  (VISION_PROVIDER=cloud, reserved)
```

- **Local provider:** the validated in-process implementation. It is the reference
  implementation and the fallback.
- **Cloud provider:** a placeholder only, for running the **same model and weights**
  on managed GPU infrastructure. It returns `503` until implemented, and never
  switches silently to another model.
  - A real implementation must return the same `VisionScreenResponse`, verify the
    same weights SHA-256, and keep uploads out of logs.
- **Browser independence:** the browser only calls `POST /api/v1/vision/screen` and
  cannot tell which provider served the request.
- **Unknown values:** an unknown `VISION_PROVIDER` value also returns `503`.

### Model preload (optional)

- **Enable:** set `VISION_PRELOAD=1`. Application startup then loads the local model
  in a background daemon thread.
- **Why:** it removes the first-request cold start. Measured in the browser, the first
  request took **250 ms**, versus about 3.4 s with lazy loading.
- **Failure handling:** startup is never blocked. A load failure is logged, and
  requests then return `503`.
- **Default:** off, which keeps tests and CPU-only setups unchanged.
- **Recommendation:** turn it on for demos.

### Request flow

```
upload (in memory, size-limited)
  -> preprocessing.preprocess          (outside lock)
  -> [model lock] scores -> Grad-CAM   (serialized)
  -> heatmap/overlay PNG rendering     (outside lock)
  -> VisionScreenResponse
  -> audit log entry
```

### Integration with the existing backend

- **Authentication:** the endpoint requires the existing session authentication
  (`dependencies.auth.get_current_user`).
- **Audit log:** it writes one entry through the existing `log_action` helper
  (`routers/medical_data.py`). The entry has action `vision_screen` and records only
  the input format, the weights ID, and the Grad-CAM target. No image data and no
  DICOM metadata are logged.
- **Router registration:** the router is registered in `backend/main.py`, like the
  other `/api/v1/*` routers.
- **Lazy import:** `routers/vision.py` imports torch only inside the request
  handler. The backend therefore still starts where the vision stack is not
  installed; the endpoint then returns `503`.
- **No persistence:** there is no new database table and no storage write. Uploaded
  bytes are processed in memory and discarded.
- **Other components:** Ollama and OHIF are unchanged. The frontend integration was
  added in Phase 4 (§15).

## 2. Model

| | |
|---|---|
| Name | TorchXRayVision DenseNet-121 |
| Weights | `densenet121-res224-all` (torchxrayvision 1.5.4) |
| Architecture | DenseNet-121: growth 32, blocks 6/12/24/16, 1 input channel, 1024 → 18 linear head, 6,966,034 parameters |
| Input | `[1, 1, 224, 224]` float32, values in [−1024, 1024] |
| Runtime validated | Python 3.12.10 (python.org, PSF-signed), torch 2.6.0+cu124, torchvision 0.21.0+cu124, CUDA 12.4, cuDNN 9.1, NVIDIA RTX 3070 Ti. Phases 1–2 ran on Python 3.11.16. |

## 3. Checkpoint and SHA-256

- **Path:** `backend/models/weights/densenet121-res224-all.pt`. Override it with
  `VISION_WEIGHTS_PATH`.
- **Expected SHA-256:** `56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899`.
- **Upstream file:** `nih-pc-chex-mimic_ch-google-openi-kaggle-densenet121-d121-tw-lr001-rot45-tr15-sc15-seed0-best.pt`
  from the TorchXRayVision v1 release.

### Loading (`model.load_model`)

1. Compute the SHA-256 of the file. A missing file or a hash mismatch raises
   `VisionModelError`, and the API returns `503` with a generic message. The hash is
   checked **before** deserialization, because the checkpoint is a full pickle
   (`torch.load(weights_only=False)`).
2. Build the TorchXRayVision `DenseNet` architecture and load the state dict from the
   verified file.
3. Set the same attributes that `xrv.models.DenseNet(weights=...)` sets: `targets`,
   `op_threshs`, `input_resolution`, and `apply_sigmoid=False`.

The TorchXRayVision constructor is not called with `weights=` because it downloads
the checkpoint when its cache copy is missing. The service **never downloads
weights**. A test checks that the locally loaded model produces bit-identical
outputs to the TorchXRayVision constructor.

### Device selection

`VISION_DEVICE` accepts:

| Value | Behavior |
|---|---|
| `auto` (default) | `cuda:0` if available, otherwise CPU |
| `cuda` | CUDA; fails if CUDA is unavailable |
| `cpu` | CPU |

The model is moved to the device once at load time. Only the input tensor moves per
request.

### Load once

`get_vision_model()` is a thread-safe, lazily initialized process singleton that
uses double-checked locking. After loading, one warm-up forward and backward pass
runs on a synthetic intensity ramp, so the first real request does not pay CUDA
start-up cost. The warm-up output is discarded.

## 4. Preprocessing

This is pixel-intensity preprocessing for radiographs. CT intensity units are not
involved.

| Step | PNG / JPEG | DICOM |
|---|---|---|
| Detect | PNG signature / JPEG SOI marker | `DICM` at byte offset 128 (DICOM Part 10) |
| Decode | Pillow | pydicom 3.0.2 (native, JPEG Baseline via Pillow) |
| Grayscale | `L` → maxval 255; `I;16*` → 65535; `I` (within 16-bit range) → 65535; other modes (RGB, RGBA, P, …) → `convert("L")`, 255 | `SamplesPerPixel` must be 1; `PhotometricInterpretation` must be MONOCHROME1/2 |
| Intensity | — | Modality LUT / rescale if present; VOI LUT / window if present; after any LUT, min-max scale to [0, 255]; otherwise maxval = 2^BitsStored − 1 |
| Polarity | — | MONOCHROME1 is inverted (`maxval − x`); MONOCHROME2 is unchanged |
| Normalize | `xrv.utils.normalize(img, maxval)` → [−1024, 1024] | same |
| Crop | `xrv.datasets.XRayCenterCrop` (square on the short side) | same |
| Resize | `F.interpolate(bilinear, align_corners=False)` → 224×224 | same |
| Check | shape `[1,1,224,224]`, all finite | same |

### Validation rules (not part of the Phase 2 script)

These checks add input validation without changing the numeric path:

- **DICOM content:**
  - `Modality` must be `CR`, `DX`, or empty.
  - Multi-frame DICOM is rejected, as is DICOM without pixel data.
  - The pixel array shape must match `Rows`/`Columns`.
- **Pixel values:** without a LUT, DICOM values must lie within
  `[0, 2^BitsStored − 1]`; Phase 2 had no explicit check for this.
- **Image size:** minimum side 64 px, maximum 144 megapixels. Pillow's
  decompression-bomb warnings are treated as errors.

### Equivalence with Phase 2

The numeric path is the same as Phase 2. For the NIH PNG and the SIIM DICOM, the
tests assert that the service tensor is **bit-identical** (`torch.equal`) to the
Phase 2 validation script's output.

JPEG input is new in Phase 3. It uses the same Pillow path as PNG and is covered by a
test.

## 5. Supported inputs

| Format | Notes |
|---|---|
| PNG | 8-bit or 16-bit grayscale; color is converted to luminance |
| JPEG | Converted to grayscale if needed |
| DICOM (Part 10) | CR/DX, single frame, MONOCHROME1/2. Transfer syntaxes: uncompressed and those the installed decoders handle, verified with JPEG Baseline. JPEG-LS, JPEG 2000, and similar need extra decoder packages that are not installed; the API returns `422` for them. |

Upload limit: `VISION_MAX_UPLOAD_BYTES`, default 50 MiB (the same as the existing
DICOM upload). The limit is enforced while the upload is read.

## 6. The 18 model outputs

Atelectasis, Consolidation, Infiltration, Pneumothorax, Edema, Emphysema, Fibrosis,
Effusion, Pneumonia, Pleural_Thickening, Cardiomegaly, Nodule, Mass, Hernia,
Lung Lesion, Fracture, Lung Opacity, Enlarged Cardiomediastinum.

## 7. Score semantics

- **How scores are produced:** TorchXRayVision's `forward()` applies `sigmoid` and
  then `op_norm` with the model's per-output operating thresholds. The service uses
  that output **directly** and applies no second sigmoid.
- **Test coverage:**
  - Scores equal `op_norm(sigmoid(logits))` applied exactly once.
  - Some scores fall below 0.5, which a double sigmoid could never produce.
  - The NIH sample reproduces the Phase 2 Cardiomegaly score of 0.6600.
- **Interpretation:** a score of 0.5 corresponds to the model's operating point.
  Scores are **model scores**, not calibrated clinical probabilities and not
  diagnoses. No calibration has been performed.
- **Primary finding:** `primary_finding` is the highest-scoring output. Ties go to the
  output listed first.

## 8. Grad-CAM

- **Target layer:** `features.denseblock4`, output shape `[1, 1024, 7, 7]`.
  - **Why not `features.norm5`:** TorchXRayVision applies an in-place ReLU to that
    output, which conflicts with full backward hooks. This was established in Phase 2.
- **Target:** by default, the highest-scoring output. An optional `target` form field
  selects any other model output by exact name. Names that are not model outputs
  (for example "Abnormality") return `422`. There is no generic abnormal/normal
  target.
- **Method:**
  1. A forward hook captures activations.
  2. A full backward hook captures the gradient of the selected output's score.
  3. α = spatial mean of the gradient.
  4. CAM = ReLU(Σ α·A).
  5. Bilinear upsample to 224×224, then min-max normalization to [0, 1].
- **Cleanup:** hooks are removed and parameter gradients are cleared after every call.
- **Rendering:** numpy + Pillow only, no matplotlib.
  - **Original:** a grayscale PNG of the center-cropped region the model analyzed.
    Browsers cannot display DICOM, so this is returned for every input format; the
    heatmap and overlay align to it.
  - **Heatmap:** a JET colormap PNG at 224×224, in model input space.
  - **Overlay:** 0.55 × original + 0.45 × JET over the center-crop region of the
    original image.
  - **Size change from Phase 2:** the original and overlay are downscaled to at most
    `VISION_MAX_OVERLAY_SIDE` pixels (default 1024). Phase 2 rendered at native
    resolution.
- **Encoding:** all three images are returned as base64 PNG, compression level 1
  (lossless).
- **Tests:**
  - The heatmap is class-specific: its correlation with the heatmap for the
    lowest-scoring output is below 0.99.
  - The score recomputed in the gradient pass equals the inference score.
  - The heatmap is finite and non-zero.
- **What it shows:** Grad-CAM is an attention visualization of what influenced the
  selected model output. **It is not proof or localization of disease.**

## 9. Concurrency model

- **One lock per model** (`VisionModel.lock`, a `threading.Lock`) serializes
  inference and Grad-CAM.
- **Why:** Grad-CAM registers hooks on a shared layer, zeroes and accumulates
  parameter gradients, and runs a backward pass. Concurrent requests on the same
  module could mix hook captures and gradients.
- **What runs outside the lock:** decoding, preprocessing, and PNG rendering, so they
  can run in parallel.
- **Threading:** the route handler runs the service in FastAPI's threadpool
  (`run_in_threadpool`), so the event loop is not blocked.
- **Test coverage:** six concurrent requests run with a peak of one Grad-CAM at a
  time, the lock held during every Grad-CAM, and results identical to sequential
  runs.

## 10. API

### `POST /api/v1/vision/screen`

- **Authentication:** existing session cookie. The test environment uses the
  existing fallback user.
- **Body:** `multipart/form-data`
  - `file` (required): PNG, JPEG, or DICOM
  - `target` (optional): an exact model output name for Grad-CAM

| Status | When |
|---|---|
| 200 | Success |
| 400 | Empty upload, corrupt/truncated image, invalid DICOM pixel data |
| 401 | Not authenticated |
| 413 | Upload exceeds `VISION_MAX_UPLOAD_BYTES` |
| 415 | Not PNG, JPEG, or DICOM Part 10 |
| 422 | Unsupported DICOM (modality, color, multi-frame, undecodable transfer syntax, no pixel data), image too small or too large, unknown `target`, missing `file` |
| 503 | Vision stack not installed, or checkpoint missing or failed verification |
| 500 | Unexpected failure (details logged server-side only) |

### What the response never contains

- filesystem paths or the checkpoint path
- the upload filename
- patient, institution, or other DICOM identifying metadata

The input description contains only format, dimensions, PIL mode or photometric
interpretation, bits stored, modality, transfer syntax, and the preprocessing steps.

## 11. Response schema (`VisionScreenResponse`)

```jsonc
{
  "model": {
    "name": "TorchXRayVision DenseNet-121",
    "architecture": "DenseNet-121 (growth 32, blocks 6/12/24/16, 1 input channel, 18 outputs)",
    "weights": "densenet121-res224-all",
    "weight_sha256": "56524913…8899",
    "targets": 18,
    "target_list": ["Atelectasis", "…"],
    "device": "cuda:0 (NVIDIA GeForce RTX 3070 Ti)",
    "input_size": 224,
    "score_semantics": "Model score from TorchXRayVision … not a calibrated clinical probability and not a diagnosis."
  },
  "input": {
    "format": "png | jpeg | dicom",
    "width": 512,
    "height": 512,
    "source_mode": "L | MONOCHROME2 | …",
    "bits_stored": 8,
    "modality": null,
    "transfer_syntax": null,
    "preprocessing": ["PNG decoded 512x512; …", "xrv.utils.normalize(maxval=255) -> [-1024, 1024]", "…"]
  },
  "primary_finding": { "pathology": "Cardiomegaly", "score": 0.6600 },
  "findings": [ { "pathology": "Cardiomegaly", "score": 0.6600 } /* all 18, highest first */ ],
  "explanation": {
    "method": "Grad-CAM",
    "target_pathology": "Cardiomegaly",
    "target_score": 0.6600,
    "target_layer": "features.denseblock4",
    "description": "Grad-CAM visual explanation … not proof or localization of disease, and requires clinical review.",
    "original": { "media_type": "image/png", "encoding": "base64", "width": 512, "height": 512, "data": "…" },
    "heatmap": { "media_type": "image/png", "encoding": "base64", "width": 224, "height": 224, "data": "…" },
    "overlay": { "media_type": "image/png", "encoding": "base64", "width": 512, "height": 512, "data": "…" }
  },
  "timing": { "preprocessing_ms": 4.7, "inference_ms": 15.5, "gradcam_ms": 37.3, "rendering_ms": 19.0, "total_ms": 77.9 },
  "inferred_at": "2026-09-17T…Z",
  "safety": {
    "message": "AI-generated screening assistance — not a diagnostic determination. Consult a qualified healthcare professional.",
    "requires_clinical_review": true
  }
}
```

The response is about 0.55 MB for a 512 px input and about 1.85 MB for a 1024 px
input, mostly the base64 overlay.

## 12. Safety language

- **Safety notice:** every successful response carries the exact message above and
  `requires_clinical_review: true`.
- **Wording:** responses use "model score", "model finding", "screening output",
  "visual explanation", and "requires clinical review".
- **Banned-wording test:** a test fails if a response contains "diagnosed",
  "confirmed", "definitely", "patient has", "safe" (as a standalone word), or
  "clinically proven".
- **Grad-CAM wording:** always described as an explanation or attention
  visualization, never as evidence of disease.

## 13. Performance (measured baseline)

- **Machine:** RTX 3070 Ti (8 GB, driver 610.88), AMD64 CPU, Windows 11,
  Python 3.12.10, torch 2.6.0+cu124.
- **Method:** measured after one first request. CUDA is synchronized around the GPU
  sections.

### Real HTTP

- **Setup:** uvicorn on `127.0.0.1`, authenticated `httpx` client, 30 requests per
  sample. Server timings come from the response's `timing` field.
- **Results:** `backend/tests/artifacts/vision_http_verification.json`. This file also
  holds the 29 functional HTTP checks (all passed).

| | NIH PNG 512² (median / P95) | SIIM DICOM 1024² (median / P95) |
|---|---|---|
| **HTTP request latency (client)** | **99.84 / 118.03 ms** | **184.70 / 202.66 ms** |
| Preprocessing | 5.38 / 6.84 ms | 18.08 / 19.24 ms |
| Inference | 16.37 / 20.66 ms | 16.16 / 19.80 ms |
| Grad-CAM | 41.93 / 51.04 ms | 44.53 / 60.45 ms |
| Rendering (PNG + base64) | 22.48 / 25.09 ms | 83.09 / 87.49 ms |
| Service total | 87.12 / 101.96 ms | 163.12 / 181.99 ms |
| Response size | 556 KB | 1,853 KB |

- **What HTTP latency adds:** the difference between HTTP latency and service total
  is multipart upload parsing, auth and database dependencies, the audit write, JSON
  serialization, and transfer.
- **First request:** the **first request after server start took 3.43 s**, because
  the model loads lazily on first use (torch import, hash, load, warm-up).

### In-process

- **Script:** `backend/tests/benchmark_vision_service.py`, 50 requests per sample.
  Results are in `backend/tests/artifacts/vision_service_benchmark.json`.
- **Model load (once per process):**
  - 351 ms for hashing, building, deserializing, and moving to the GPU.
  - 908 ms including the warm-up pass.
- **Service total (median):** NIH 86.5 ms, SIIM 169.4 ms. It ran while the idle HTTP
  server shared the GPU. The earlier Python 3.11 run measured 77.9 ms and 150.4 ms.

### GPU memory

Measured with the PyTorch allocator in-process:

- 43.3 MB allocated after load.
- **184.6 MB peak allocated.**
- 210 MB peak reserved.

Whole-device usage from `nvidia-smi` went from 1,288 MB to 1,763 MB when the server
loaded the model. That figure includes the CUDA context; Windows (WDDM) does not
report per-process usage.

### How to read these numbers

- **Phase 2 reference** (standalone script): inference ~14 ms, Grad-CAM ~36 ms,
  end-to-end ~68 ms. The service adds overlay/PNG rendering, response building, and,
  over HTTP, request handling. Rendering cost grows with image size.
- **Scope:** these are engineering measurements on one machine, not guarantees and
  not clinical workflow performance.

## 14. Limitations

- **Clinical validity:** **the model has not been clinically validated by HoloMed.**
  Phase 2 validated software execution on two public images only. There are no
  accuracy, calibration, or clinical performance claims.
- **Model scope:** the model is trained on public adult chest radiograph datasets.
  - It has 18 fixed outputs and no "normal" output.
  - Behavior on AP or lateral views, pediatric images, other scanners, or images
    with devices is not characterized.
  - The service does not verify that an image is a chest radiograph beyond format,
    DICOM modality, and size checks.
- **Grad-CAM:** coarse resolution (7×7 upsampled), and min-max normalization hides
  absolute magnitude. It shows model sensitivity, not anatomy or pathology.
- **Throughput:** requests are serialized through one model lock, so throughput is
  bounded by one Grad-CAM at a time per process.
- **Lazy model load:** the model loads on the first request, which took about 3.4 s
  over HTTP.
- **Environment history:**
  - **Problem:** the original uv-managed Python 3.11.16 venv could not load its
    unsigned `_ssl.pyd` under Windows Application Control, so FastAPI could not
    serve requests there.
  - **Fix:** the project `.venv` was recreated from the PSF-signed python.org Python
    3.12.10, with the same package versions. The full backend suite (including the
    ASGI and full-app vision tests) and the real HTTP checks now run.
  - **Test design:** the vision API tests still include a "direct" variant that calls
    the route handler without anyio. The "asgi" variants skip automatically only where
    `ssl` cannot be loaded.
  - **matplotlib:** it was blocked under the old interpreter and is not a dependency
    of the service.
- **Checkpoint warnings:** `torch.load` emits `SourceChangeWarning` for the pickled
  TorchXRayVision model classes. This is expected for a full-model pickle; the file
  hash is verified first.
- **Dependencies:**
  - `backend/requirements.txt` pins `torch==2.6.0` and `torchvision==0.21.0` with the
    CUDA 12.4 index as an extra index.
  - TorchXRayVision's own dependencies (scikit-image, pandas, requests, imageio,
    tqdm) are left to the resolver.
  - The root-level `requirements.txt` was not changed.

## 15. Frontend integration (Phase 4)

**Location:** Imaging Workspace (the default page after login) → **AI Screening**
mode (the default). The existing OHIF viewer is unchanged and sits behind the
**OHIF Viewer** mode switch.

### Workflow

1. Select or drop a PNG, JPEG, or DICOM file. The client checks its signature and
   size (50 MB); the backend re-validates everything.
   - PNG and JPEG get a local preview through an object URL.
   - DICOM is decoded by the backend and shown after screening.
2. **Run AI Screening** sends an authenticated multipart request (session cookie via
   `lib/api.ts`), with a loading state and a 90 s timeout.
3. The results card shows:
   - the **Primary Model Finding** and its **Model Score** (4 decimals, labelled
     "Non-diagnostic model output")
   - **All Model Findings**: the 18 returned outputs, sorted by score, with bars
   - the safety sentence and a **Requires Clinical Review** badge
4. Selecting a finding requests the **same endpoint** with `target=<finding>`.
   - The Grad-CAM for that output comes from the backend.
   - Results are cached per finding for the current image.
   - The primary finding does not change.
5. **Visual Explanation** viewer:
   - **Original / Grad-CAM / Overlay** views and an **overlay opacity** slider.
   - The overlay stacks the backend's heatmap PNG over the backend's `original` PNG
     with CSS opacity. At 45 % it matches the backend's own blend.
   - Caption: "Visual explanation of the selected model output … This visualization
     does not establish the presence or absence of disease."
6. **Model Information** shows the model, weights, SHA-256 (shortened; the full value
   is in the tooltip), the 18 targets, Grad-CAM with its layer, "Non-diagnostic model
   output", the input description, and the analysis time.
7. **Processing Time** shows the backend's `timing` fields for that request, plus the
   round trip measured in the browser.
8. A **Safety Notice** ("AI-generated information — not a diagnosis. Consult a
   qualified healthcare professional." / "Requires clinical review.") and a
   **Human review** note are always visible.

### Error handling

Users see plain messages; raw server text is never displayed.

| Condition | Message title |
|---|---|
| 401 | Session expired (with a **Sign in again** action) |
| 400 | Image could not be read |
| 413 | File too large |
| 415 or failed client signature check | Unsupported file type |
| 422 | Image not supported for screening / Finding not available |
| 500 / 502 / 503 / 504 (including a stopped backend behind the Vite proxy) | Screening unavailable |
| fetch network error | Backend unreachable |
| client timeout | Request timed out |

### Security

- The browser talks only to the HoloMed origin; there are no model-provider calls and
  no API keys.
- Images are never written to local or session storage, and preview object URLs are
  revoked.
- Nothing is logged to the console.
- Filesystem paths and DICOM identifiers are not shown.

### Deployment notes

- The frontend uses `VITE_API_BASE_URL`; the default is same-origin `/api`, proxied to
  `127.0.0.1:8001` by `vite.config.ts` in development.
- The backend is configured with:
  - `VISION_PROVIDER`
  - `VISION_PRELOAD`
  - `VISION_DEVICE`
  - `VISION_WEIGHTS_PATH`
  - `VISION_MAX_UPLOAD_BYTES`
  - `VISION_MAX_OVERLAY_SIDE`
