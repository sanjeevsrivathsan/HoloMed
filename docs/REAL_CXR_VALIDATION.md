# Real Chest X-Ray Validation (Phase 2)

> **Research/Engineering Validation — Not a Diagnostic Result.**
> This document records a software/model execution check on public, de-identified
> chest radiographs. It makes no claim about diagnostic accuracy, clinical safety,
> clinical effectiveness, patient outcomes, or regulatory compliance.

- **Script:** `backend/tests/validate_real_cxr.py`
- **Machine-readable results:** `backend/tests/artifacts/real_cxr/validation_report.json`
- **Run log:** `backend/tests/artifacts/real_cxr/run_log.txt`
- **Run:** 2026-09-17 01:30 UTC. **Status: PASS** (65/65 checks).

## 1. Objective

Confirm that the selected model (TorchXRayVision DenseNet-121, weights
`densenet121-res224-all`) runs end to end on real chest radiographs before it is
wrapped in the HoloMed-D vision service (Phase 3). The pipeline covers:

1. ingestion (PNG and DICOM)
2. radiographic preprocessing
3. inference
4. all 18 model outputs
5. class-specific Grad-CAM
6. timing and GPU memory
7. validation artifacts

### Precondition: Phase 1 was corrected and re-run

Before Phase 2, two fixes were made to `backend/tests/validate_model.py`:

- **Double sigmoid.** The script applied `torch.sigmoid` to outputs that
  TorchXRayVision had already passed through `sigmoid` + `op_norm`. That squeezed
  every score into [0.50, 0.73]. The model output is now used directly.
- **GPU name.** The name was hardcoded; it is now detected at runtime.

The corrected Phase 1 run was first written to a scratch directory. It passed:

- 18 outputs, all finite, all in [0.1096, 0.6103]
- CUDA inference on an RTX 3070 Ti: mean 13.02 ms, P95 13.62 ms
- VRAM peak 43.7 MB
- Grad-CAM gradient norm 0.0128, no NaN/Inf

The weights SHA-256 was verified. Only after this run passed were the Phase 1
artifacts replaced; the log is `backend/tests/artifacts/phase1_run_log.txt`.

## 2. Dataset / source

| Case | Role | Dataset | Retrieved from |
|---|---|---|---|
| `nih_png` | **Primary** | NIH ChestX-ray14 (NIH Clinical Center). Reference: <https://nihcc.app.box.com/v/ChestXray-NIHCC>; Wang et al., CVPR 2017 | TorchXRayVision repo `tests/00000001_000.png` at commit `be1cefcc4967c1143520070fb7d760dc3d485e07` |
| `siim_dicom` | Secondary (DICOM path) | SIIM-ACR Pneumothorax Segmentation, whose images are derived from NIH ChestX-ray14. Reference: <https://www.kaggle.com/c/siim-acr-pneumothorax-segmentation> | TorchXRayVision repo `tests/1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm`, same commit |

### Rejected candidates

- **Local OHIF test data, `dcm/overlay/overlayJLS.dcm`.** Its `InstitutionName`
  is a veterinary faculty, so it is likely not a human chest radiograph. It is also
  JPEG-LS compressed, and no decoder is installed.
- **`backend/tests/artifacts/public_cxr_sample.png`.** It is a 14-byte
  `404: Not Found` text file left by an earlier failed download. It was not used
  and was left untouched.
- **TorchXRayVision `Fake_MONOHR1.dcm`.** It is synthetic.

## 3. Image provenance

Full record: `backend/tests/artifacts/real_cxr/provenance.json`.

| Case | SHA-256 | Git blob SHA-1 (matches GitHub API) | Size |
|---|---|---|---|
| `nih_png` | `c8cbe59e6b9b186060dc68e63965658fa6b5b3ada6648d25c189b8b69b43cd4c` | `dfe0b95676e97ed4d473872caedce2ffa44b4ebc` | 182,547 B |
| `siim_dicom` | `13d378bfe1af0724e8cbe51adde36882cfdc6a69361c8a48ac30f688c3af7613` | `8e9c527a0fc3db22488f3876461a9fc8ed5ba9a9` | 127,290 B |

### How the originals are protected

- The originals live in `backend/tests/artifacts/real_cxr/source/` and are marked
  read-only.
- The script checks each file's SHA-256 against `provenance.json` before
  processing, and checks that the hash is unchanged afterwards.
- All derived files are written next to `source/`, never inside it.

### De-identification

- **NIH ChestX-ray14** is a public, de-identified NIH Clinical Center release.
- **SIIM DICOM:** `PatientName`/`PatientID` are random UUIDs, `StudyDate` is the
  placeholder `19010101`, and there is no institution tag.

### Licensing

SIIM-ACR data is distributed under Kaggle competition rules. Review its licensing
before committing the DICOM to a repository.

## 4. Input format

| | `nih_png` | `siim_dicom` |
|---|---|---|
| Container | PNG | DICOM, JPEG Baseline (Process 1) |
| Modality | Chest radiograph (NIH release has no DICOM tag) | `CR` |
| Body part | chest | `CHEST` |
| Projection | PA (dataset `View Position`) | PA (`ViewPosition`) |
| Pixels | 512×512, 8-bit grayscale (`L`) | 1024×1024, 8 bits stored, `MONOCHROME2`, 1 sample |
| Notes | Downsampled repository copy. The dataset lists the original size as 2682×2749. | No Modality LUT, rescale, VOI LUT, or window tags |

## 5. Preprocessing

This is pixel-intensity preprocessing for a chest radiograph. No CT-style
intensity units are involved.

### PNG path (`nih_png`)

1. Read with PIL, mode `L`. `maxval = 255`.
2. `xrv.utils.normalize(img, 255)`: `(2·img/255 − 1)·1024`, giving the range [−1024, 1024].
3. `xrv.datasets.XRayCenterCrop`: a square crop on the short side. The image is
   512×512, so the crop is the whole image (y0 = 0, x0 = 0).
4. `torch.nn.functional.interpolate`, bilinear, `align_corners=False`, to 224×224.
5. The result is a float32 tensor `[1, 1, 224, 224]`, range [−1024.0, 1017.0], with no NaN/Inf.

### DICOM path (`siim_dicom`)

1. Decode with `pydicom.dcmread(...).pixel_array` (pydicom 3.0.2, JPEG Baseline
   via Pillow). This gives 1024×1024 with values in [0, 254].
2. Apply the Modality LUT / rescale if present. Not present here.
3. Apply the VOI LUT / window if present. Not present here.
   - If either LUT is applied, the image is min-max rescaled to [0, 255].
4. Handle photometric interpretation:
   - `MONOCHROME2`: no inversion.
   - `MONOCHROME1`: inverted as `maxval − img`.
   - Anything else is rejected.
5. `maxval = 2^BitsStored − 1 = 255`.
6. Steps 2–5 of the PNG path follow. The resulting tensor has range [−983.3, 941.7] with no NaN/Inf.

### Deliberate Phase 2 preprocessing choice

Phase 2 adds `XRayCenterCrop` before resizing. Phase 1 resized directly without
cropping. **Phase 2 therefore does not exactly reproduce Phase 1 preprocessing.**

- The crop is TorchXRayVision's own transform, and it prevents distorting the
  aspect ratio of non-square radiographs.
- For both images here the input was square, so the crop had no effect.
- The resize step (bilinear `F.interpolate`) is the same as in Phase 1.
  TorchXRayVision's own `XRayResizer` uses skimage instead.

## 6. Model

- **Architecture:** TorchXRayVision `DenseNet`, DenseNet-121 layout (growth rate 32,
  blocks 6/12/24/16, one input channel, 1024 → 18 linear classifier).
  6,966,034 parameters.
- **Package versions:** torchxrayvision 1.5.4, torch 2.6.0+cu124 (CUDA 12.4, cuDNN 90100), Python 3.11.16.
- **Loading:** `xrv.models.DenseNet(weights="densenet121-res224-all")`, `eval()` on `cuda:0`. Load time 246.8 ms.
- **Output semantics:** `forward()` applies `sigmoid` followed by `op_norm` with the
  model's per-class operating thresholds (`op_threshs`). A value of 0.5 corresponds
  to the model's operating threshold.
  - These values are **model scores, not calibrated diagnostic probabilities**. No
    calibration was performed.
  - No further transformation is applied.

## 7. Weight provenance

- **Upstream:** <https://github.com/mlmed/torchxrayvision/releases/download/v1/nih-pc-chex-mimic_ch-google-openi-kaggle-densenet121-d121-tw-lr001-rot45-tr15-sc15-seed0-best.pt>
- **Local validated copy:** `backend/models/weights/densenet121-res224-all.pt` (27.07 MB).
- **File TorchXRayVision actually loads:**
  `%USERPROFILE%\.torchxrayvision\models_data\nih-pc-chex-mimic_ch-google-openi-kaggle-densenet121-d121-tw-lr001-rot45-tr15-sc15-seed0-best.pt`.
- **Fail-loud check:** the script asserts that the loaded file is byte-identical
  (same SHA-256) to the local validated copy. Loading different weights would fail
  the run rather than go unnoticed.

## 8. SHA-256

`56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899`.
The local copy and the file TorchXRayVision loads have the same hash, and it
matches the value validated in Phase 1.

## 9. Model outputs

All 18 targets were present, finite, and in [0, 1].

The values are threshold-rescaled model scores, not calibrated probabilities and
not diagnoses.

| # | Target | `nih_png` | `siim_dicom` |
|---|---|---|---|
| 0 | Atelectasis | 0.5050 | 0.5544 |
| 1 | Consolidation | 0.3059 | 0.5100 |
| 2 | Infiltration | 0.5154 | 0.5257 |
| 3 | Pneumothorax | 0.2487 | 0.5030 |
| 4 | Edema | 0.2743 | 0.0119 |
| 5 | Emphysema | 0.5036 | 0.5008 |
| 6 | Fibrosis | 0.5330 | 0.5332 |
| 7 | Effusion | 0.4029 | 0.2388 |
| 8 | Pneumonia | 0.3095 | 0.2897 |
| 9 | Pleural_Thickening | 0.5103 | 0.5585 |
| 10 | Cardiomegaly | **0.6600** | 0.0524 |
| 11 | Nodule | 0.5092 | 0.5299 |
| 12 | Mass | 0.3226 | **0.5589** |
| 13 | Hernia | 0.0119 | 0.0573 |
| 14 | Lung Lesion | 0.2223 | 0.0032 |
| 15 | Fracture | 0.3238 | 0.5186 |
| 16 | Lung Opacity | 0.2775 | 0.3295 |
| 17 | Enlarged Cardiomediastinum | 0.4101 | 0.1563 |

## 10. Selected Grad-CAM target

- **Rule:** use the highest-scoring valid model output (a non-empty pathology name
  with a defined operating threshold).
- **No generic targets:** no "abnormality" or "normal/abnormal" target was created.

| Case | Grad-CAM target | Output index | Model score |
|---|---|---|---|
| `nih_png` | **Cardiomegaly** | 10 | 0.6600 |
| `siim_dicom` | **Mass** | 12 | 0.5589 |

## 11. Grad-CAM layer

**Target layer: `features.denseblock4`**, the same layer as Phase 1.

### Why not `features.norm5`

TorchXRayVision's `features2()` applies an in-place ReLU to the `norm5` output,
which conflicts with PyTorch full backward hooks.

### Method

1. Forward hook stores the activations `[1, 1024, 7, 7]`.
2. Full backward hook stores the gradient of the selected output's score, `[1, 1024, 7, 7]`.
3. Channel weights α = spatial mean of the gradient.
4. CAM = ReLU(Σ α·A).
5. Bilinear upsample to 224×224, then min-max normalization.

### Checks

| Check | `nih_png` | `siim_dicom` |
|---|---|---|
| Gradient norm | 0.01255 | 0.00656 |
| Raw CAM max | 0.01510 | 0.00621 |
| Pixels > 0.2 after normalization | 21.3 % | 46.6 % |
| Heatmap | 224×224, finite | 224×224, finite |
| Grad-pass score equals inference score | yes | yes |
| Class-specific: correlation with the CAM of the lowest-scoring output | −0.341 (vs Hernia) | 0.056 (vs Lung Lesion) |

### Overlay

The overlay is drawn on the original radiograph at native resolution, over the
center-crop region (the full image here). The heatmap is upsampled with bilinear
interpolation and blended at 0.55 × image + 0.45 × JET colormap.

### What the heatmap is not

The heatmap marks the image regions that influenced the selected model output. It
is **not proof or localization of disease.**

## 12. Runtime

- **Hardware:** NVIDIA GeForce RTX 3070 Ti (8 GB) and an AMD64 CPU (Family 25
  Model 117), Windows 11 (build 26200).
- **Warm-up:** 20 inferences plus 3 Grad-CAM passes before any timed section.
- **Timing method:** `time.perf_counter()`, with `torch.cuda.synchronize()` before
  and after every timed GPU section.
- **Sample sizes:** inference n=100, Grad-CAM n=20, ingestion/preprocessing n=20 (CPU).

| Section | `nih_png` median / P95 | `siim_dicom` median / P95 |
|---|---|---|
| Ingestion (decode) | 1.847 / 2.161 ms | 6.472 / 7.035 ms |
| Preprocessing (CPU) | 1.232 / 1.346 ms | 5.612 / 6.258 ms |
| Inference (GPU) | 13.778 / 18.256 ms | 13.729 / 14.620 ms |
| Grad-CAM (GPU, forward + backward) | 36.035 / 38.324 ms | 36.106 / 37.612 ms |
| End-to-end single pass (warm) | 68.343 ms | 68.211 ms |
| First inference before warm-up | 302.714 ms | 15.633 ms (process already warm) |

- **Model load:** 246.8 ms.
- **End-to-end** means decode + preprocess + host-to-device copy + inference +
  Grad-CAM. It excludes model load and artifact writing.
- **Scope:** these are measurements from a single engineering machine. They do not
  represent clinical workflow performance.

## 13. GPU memory

Measured with `torch.cuda` allocator statistics; the peak was reset before each section.

| Metric | Value (both cases) |
|---|---|
| Baseline allocated (model loaded) | 70.03 MB |
| Inference peak allocated | 77.88 MB |
| Grad-CAM peak allocated | 177.22 MB |
| Peak reserved | 190.0 MB |

## 14. Ground-truth information

Dataset annotations are kept separate from model scores and are read at runtime
from the dataset files bundled with torchxrayvision 1.5.4.

### `nih_png`

- **Source:** `Data_Entry_2017_v2020.csv.gz`.
- **Finding Labels:** `Cardiomegaly`. **View Position:** PA.
- **Statement:** The dataset annotation for this image indicates Cardiomegaly,
  while the model produced a Cardiomegaly score of 0.6600.
- **Caveat:** NIH ChestX-ray14 labels were derived from radiology reports by
  NLP/text mining. They are **not** radiologist-confirmed per-image ground truth
  and have known label noise.

### `siim_dicom`

- **Source:** `siim-pneumothorax-train-rle.csv.gz`.
- **Annotation:** `EncodedPixels = -1`, meaning no pneumothorax mask was annotated.
- **Statement:** The dataset annotation for this image indicates no pneumothorax,
  while the model produced a Pneumothorax score of 0.5030. That score is just above
  the model's 0.5 operating-threshold point.
- **Caveat:** The SIIM-ACR annotation covers pneumothorax only. It says nothing
  about the Mass target selected for Grad-CAM or any other output.

No accuracy, sensitivity, specificity, or AUC is computed. A single image per
dataset cannot support such a measurement.

## 15. Results

**Phase 2 status: PASS — 65/65 checks.**

| Checklist item | Result |
|---|---|
| Verified real CXR loaded | PASS (both cases) |
| Provenance recorded | PASS |
| Original preserved | PASS (read-only; SHA-256 unchanged before/after) |
| Preprocessing succeeds | PASS |
| 224×224 tensor produced | PASS |
| No NaN/Inf | PASS |
| Correct model loaded | PASS (architecture, 18-target list, SHA-256) |
| 18 outputs verified | PASS |
| Scores finite | PASS |
| Target pathology selected | PASS (Cardiomegaly / Mass) |
| Real class-specific Grad-CAM generated | PASS |
| Heatmap dimensions valid | PASS |
| Overlay generated | PASS |
| Runtime measured | PASS |
| GPU memory measured | PASS |
| Ground truth handled correctly | PASS |
| Limitations documented | PASS (§16) |
| Validation artifacts generated | PASS |
| No unrelated project files modified | PASS (see git status comparison in the Phase 2 report) |

## 16. Limitations

### Data

- Only two images were used, and both are PA radiographs of adults from the NIH
  ChestX-ray14 lineage.
- NIH ChestX-ray14 is part of this model's training mix ("nih" in the weights
  name). These images may therefore be in-distribution, or even part of the
  training set. They cannot serve as held-out evaluation data.

### Labels

- The NIH labels come from text mining of reports and are noisy.
- The SIIM label covers pneumothorax only.
- No label was used to judge correctness.

### Model

- Outputs are uncalibrated, threshold-rescaled scores.
- The model has 18 fixed targets and no "normal" output.
- The model was trained on specific public datasets and may not generalize to
  other scanners, populations, projections (AP/lateral), pediatric patients, or
  images with devices.
  - The SIIM image shows visible metallic wires/clips.

### Preprocessing assumptions

- Input is a single-channel radiograph with correct photometric interpretation.
- 8-bit sources are scaled with `maxval = 255`.
- For DICOM, windowing tags would be honored if present; neither test image had them.
- **MONOCHROME1 inversion and the LUT branches were implemented but not exercised
  by real data** (both images are MONOCHROME2 with no LUT).
- The repository NIH PNG is a downsampled copy.

### Grad-CAM

- The resolution is coarse: a 7×7 feature map upsampled to 224×224.
- Min-max normalization hides absolute magnitude; raw maxima are reported instead.
- Grad-CAM shows sensitivity of a model output, not anatomy or pathology.
- Heatmaps can highlight confounders (text markers, devices).

### Scope

- This validates software execution only.
- It does not establish diagnostic accuracy, clinical safety, clinical
  effectiveness, patient outcomes, or regulatory compliance.

### Environment

- On this machine, a Windows Application Control policy blocks matplotlib's
  compiled `_image` module, so the composite is drawn with PIL.
- The console needs `PYTHONIOENCODING=utf-8` when output is redirected; the
  default cp1252 cannot encode the scripts' box-drawing characters.
- `torch.load` emits `SourceChangeWarning` for the pickled TorchXRayVision model
  classes. This is expected with full-model pickles, and the weights hash is
  verified.
- `torch` and `torchxrayvision` are not yet listed in `requirements.txt`.

## 17. Generated artifacts

All paths are under `backend/tests/artifacts/real_cxr/`.

### Original input (read-only)

- `source/00000001_000.png`
- `source/1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm`

### Derived artifacts

| Type | Primary (`nih_png`) | Secondary (`siim_dicom`) |
|---|---|---|
| Original render | `original_real_cxr.png` (pixel-identical to source) | `siim_dicom_original_real_cxr.png` |
| Preprocessed (224×224 model input) | `real_cxr_preprocessed.png` | `siim_dicom_real_cxr_preprocessed.png` |
| Model output | `real_cxr_scores.json` | `siim_dicom_real_cxr_scores.json` |
| Grad-CAM heatmap | `real_cxr_gradcam_heatmap.png` | `siim_dicom_real_cxr_gradcam_heatmap.png` |
| Grad-CAM overlay | `real_cxr_gradcam_overlay.png` | `siim_dicom_real_cxr_gradcam_overlay.png` |
| Composite | `real_cxr_validation_composite.png` | `siim_dicom_real_cxr_validation_composite.png` |

### Validation report

- `validation_report.json`
- `run_log.txt`
- `provenance.json`

The Phase 1 synthetic artifacts in `backend/tests/artifacts/` were not
overwritten by Phase 2.

### Reproduce

```bash
cd HoloMed-D
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe backend/tests/validate_real_cxr.py
```

## 18. Conclusion

### A. Software/model execution validation: **PASSED**

On two verified public, de-identified real chest radiographs (one PNG, one DICOM),
the pipeline ran correctly end to end:

- It decoded both images.
- It produced valid 224×224 TorchXRayVision-scaled tensors.
- It loaded the hash-verified `densenet121-res224-all` weights.
- It returned 18 finite scores in [0, 1].
- It generated real, class-specific Grad-CAM heatmaps from `features.denseblock4`
  with valid dimensions and non-trivial activation.
- Runtime was measured at ~14 ms per GPU inference and ~36 ms per Grad-CAM pass.
- The original files were left unmodified.

### B. Clinical performance validation: **NOT PERFORMED, NOT CLAIMED**

No evaluation dataset, reference standard, or statistical analysis was used. For
NIH image 00000001_000, the dataset's text-mined annotation (Cardiomegaly) and the
top model score (Cardiomegaly 0.6600) are recorded side by side. This is an
observation about one image, not evidence of accuracy.
