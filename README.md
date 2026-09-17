# HoloMed — Explainable AI-Assisted Chest X-Ray Screening

HoloMed is a medical-information workspace (reports, imaging, privacy controls). Its main
feature is **explainable chest X-ray screening assistance**:

1. Upload a PNG, JPEG or DICOM chest radiograph.
2. **TorchXRayVision DenseNet-121** (`densenet121-res224-all`, SHA-256-verified) returns
   18 model scores.
3. **Grad-CAM** (`features.denseblock4`) shows which image regions influenced the selected
   model output.
4. A local language model (Ollama) explains the structured result in plain language. It never
   sees the image.
5. Every result carries a safety notice and requires clinical review.

> **Research/hackathon demonstration — not a diagnostic device.** The model has not been
> clinically validated by HoloMed. Model scores are uncalibrated model outputs, not
> probabilities of disease, and Grad-CAM is not proof of disease.

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI API: auth, reports, DICOMweb, audit, vision service, explanation service |
| `backend/services/vision/` | Model loading and hash check, preprocessing, inference, Grad-CAM, local/cloud providers |
| `backend/services/explanation/`, `backend/services/text_ai/` | Safe text explanations (Ollama / OmniRoute) |
| `backend/vision_worker/`, `deploy/modal/` | Private GPU worker and its Modal deployment |
| `frontend/` | React + Vite + Tailwind UI; `frontend/ohif/` is a prebuilt OHIF viewer (MIT) |
| `docs/` | Validation, service and deployment documentation |

## Documentation

| Document | Covers |
|---|---|
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Architecture, running locally, Modal deployment, environment variables, switching providers |
| [`docs/VISION_SERVICE.md`](docs/VISION_SERVICE.md) | Vision service design, API, safety language, performance, limitations |
| [`docs/REAL_CXR_VALIDATION.md`](docs/REAL_CXR_VALIDATION.md) | Real chest X-ray validation methodology and results |
| [`backend/models/weights/README.md`](backend/models/weights/README.md) | How to obtain and verify the model weights (not stored in Git) |
| [`.env.example`](.env.example) | Backend configuration variable names (no values) |

## Quick start (local)

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r backend/requirements.txt
# download and verify the weights (backend/models/weights/README.md); cp .env.example .env; set JWT_SECRET
.venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
cd frontend && npm install && npm run dev
```

See `docs/DEPLOYMENT.md` for details.

## Third-party components and data

- **TorchXRayVision** model and weights: https://github.com/mlmed/torchxrayvision
- **OHIF Viewer:** MIT licence, see `frontend/ohif/LICENSE`. Bundled library licences are in
  `frontend/ohif/*.LICENSE.txt`.
- **NIH ChestX-ray14** sample images (NIH Clinical Center): attribution in
  `backend/tests/artifacts/real_cxr/ATTRIBUTION.md`.
