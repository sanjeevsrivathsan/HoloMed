# HoloMed Deployment Guide

> HoloMed is a hackathon/research demonstration. It is **not** clinical software, and the model
> has not been clinically validated by HoloMed. No regulatory compliance is claimed.

> **Local GPU hosting is the primary demonstration/development deployment.**
> **Modal is an optional cloud deployment target and is not required for local operation.**

| Mode | Setting | Role |
|---|---|---|
| Local vision | `VISION_PROVIDER=local` (default) | **Primary.** DenseNet-121 on this machine's NVIDIA GPU (CPU fallback). No cloud credentials, no `VISION_CLOUD_*` and no internet access needed. |
| Local text | `TEXT_AI_PROVIDER=ollama` (default) | **Primary.** Local Ollama for explanations. |
| Cloud vision | `VISION_PROVIDER=cloud`, `VISION_CLOUD_URL=<server-side value>`, `VISION_CLOUD_TOKEN=<server-side secret>` | **Optional.** The existing Modal worker. |
| Hosted text | `TEXT_AI_PROVIDER=omniroute` + `OMNIROUTE_*` | **Optional.** Hosted OmniRoute gateway. |

The provider is always explicit. There is **no automatic fallback** in either direction
(local→cloud or cloud→local), and an unavailable configured provider returns HTTP 503.

**Status (2026-09-17)**
- **Local GPU deployment:** verified end to end on an RTX 3070 Ti (PNG, DICOM, Grad-CAM,
  Ollama explanations).
- **Cloud vision worker:** implemented and tested against a locally running worker.
- **Modal:** not yet deployed. The Modal volume and secret exist; deploying the T4 function
  requires a payment method on the Modal account.
- **Pending measurements:** cloud cold-start and latency numbers will be added after a real
  deployment.

## 1. Architecture

### Local GPU (primary, default)

```
Browser ──> Vite dev server (:5173, proxies /api and /ohif)
              └─> HoloMed FastAPI (:8001)
                    ├── VISION_PROVIDER=local  ──> in-process TorchXRayVision DenseNet-121 + Grad-CAM (GPU/CPU)
                    └── TEXT_AI_PROVIDER=ollama ──> local Ollama (:11434), explanation text only
```

### Cloud vision (optional)

```
Browser ──> HoloMed FastAPI
              ├── VISION_PROVIDER=cloud ──HTTPS + bearer token──> Modal "holomed-vision" (T4 GPU)
              │                                                    └── same DenseNet-121 + Grad-CAM code
              └── TEXT_AI_PROVIDER=ollama (development) | omniroute (hosted; not yet deployed)
```

### Design guarantees
- **Single gateway:** the browser only talks to the HoloMed API. It never sees provider URLs,
  tokens or which provider is in use.
- **No fallback:** with `VISION_PROVIDER=cloud` there is **no fallback** to local inference. A
  cloud failure returns a controlled `503 Vision service is not available`.
- **Same response everywhere:** the cloud worker returns the same `VisionScreenResponse` as the
  local provider. The backend rejects any response whose weights hash, 18-target list, Grad-CAM
  layer or score consistency does not match the validated model. Safety text is always set by the
  backend.
- **Text AI never sees images:** it receives only the structured model output. See
  `docs/VISION_SERVICE.md` §15 and the explanation service.

## 2. Model provenance and hash verification

| | |
|---|---|
| Model | TorchXRayVision DenseNet-121 (torchxrayvision 1.5.4) |
| Weights | `densenet121-res224-all` |
| SHA-256 | `56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899` |
| Obtain | `backend/models/weights/README.md` (upstream URL, size, verification command) |

- **Not in Git:** the checkpoint is not committed.
- **Hash check before loading:** local and cloud workers compute the SHA-256 **before**
  deserializing the file (it is a full pickle) and refuse to load anything else.
- **No downloads at runtime:** weights are never fetched while the service is running.
- **Validation evidence:** `docs/REAL_CXR_VALIDATION.md` (real-image validation) and
  `docs/VISION_SERVICE.md` (service design, safety language, limitations).

## 3. Environment variables (names only)

See `.env.example` for the full annotated list. Never commit real values; `.env` is git-ignored.

### Local development
| Group | Variables |
|---|---|
| Required | `JWT_SECRET` |
| Vision | `VISION_PROVIDER=local`, `VISION_PRELOAD`, `VISION_DEVICE`, `VISION_WEIGHTS_PATH` |
| Text AI | `TEXT_AI_PROVIDER=ollama`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| Optional | `HOLUMED_DB_PATH`, `CORS_ORIGINS`, `JWT_EXPIRE_MINUTES`, `VISION_MAX_UPLOAD_BYTES`, `VISION_MAX_OVERLAY_SIDE`, `VISION_RESULT_TTL_SECONDS`, `TEXT_AI_TIMEOUT_SECONDS` |

### Production / cloud (server secrets)
| Group | Variables |
|---|---|
| Vision | `VISION_PROVIDER=cloud`, `VISION_CLOUD_URL`, `VISION_CLOUD_TOKEN`, `VISION_CLOUD_TIMEOUT_SECONDS` |
| Text AI (hosted) | `TEXT_AI_PROVIDER=omniroute`, `OMNIROUTE_BASE_URL`, `OMNIROUTE_API_KEY`, `OMNIROUTE_MODEL` |
| Auth / CORS | `JWT_SECRET`, `CORS_ORIGINS`, `HOLOMED_ENV=production`, `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_SAMESITE` |
| Google Sign-In (optional) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (backend-only secret), `GOOGLE_REDIRECT_URI`, `GOOGLE_POST_LOGIN_URL` |

### Modal worker
- `VISION_WORKER_TOKEN` comes from the Modal Secret `holomed-vision-worker`.
- The image sets `VISION_WEIGHTS_PATH`, `VISION_DEVICE=cuda` and `VISION_PRELOAD=1`.

### Deploy-time options
`HOLOMED_MODAL_GPU` (default `T4`), `HOLOMED_MODAL_MIN_CONTAINERS` (default `0`, scale to zero),
`HOLOMED_MODAL_SCALEDOWN_SECONDS` (default `600`).

### Frontend
`frontend/.env.example`: `VITE_API_BASE_URL`, `VITE_OHIF_URL`. Never put secrets in `VITE_*`
variables.

## 4. Run locally

Prerequisites:
- Python 3.12 (python.org build)
- Node 18+
- NVIDIA GPU with CUDA 12.4 drivers (optional; CPU fallback works)
- Ollama

```bash
# 1. Python environment (from the repository root)
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt     # Windows path; use .venv/bin on Linux/macOS

# 1b. Optional OCR for scanned PDFs and PNG/JPEG medical reports (CPU)
.venv/Scripts/python -m pip install -r backend/requirements-ocr.txt

# 2. Model weights
#    download + verify per backend/models/weights/README.md

# 3. Configuration
cp .env.example .env        # then set JWT_SECRET (and others as needed)

# 4. Text AI (optional; screening and report review work without it; needed for AI summaries)
ollama pull qwen3:8b

# 5. Backend (run from the repository root; it serves /ohif from frontend/ohif)
VISION_PRELOAD=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001

# 6. Frontend
cd frontend && npm install && npm run dev      # http://127.0.0.1:5173
```

### Health checks
| Endpoint | Meaning |
|---|---|
| `GET /api/v1/health` | Application up |
| `GET /api/v1/ready` | Database reachable |
| `GET /api/v1/ai/status` | Text AI `{provider, model, status}` with status `connected`, `not_running`, `model_missing`, `configured` or `not_configured`. No URLs or keys. |
| `GET /api/v1/vision/status` | `{provider, provider_configured, model_ready, accelerator, status}` with status `ready`, `loading`, `standby` or `unavailable`. Contains no URLs, device names, paths or credentials. |

### Tests
```bash
.venv/Scripts/python -m pytest backend/tests                        # full backend suite
HOLOMED_LIVE_OLLAMA=1 .venv/Scripts/python -m pytest backend/tests -k live   # opt-in live Ollama test
cd frontend && npm run typecheck && npm test && npm run build   # npm test: processing-stage logic (node --test)
```

Medical report ingestion (upload, extraction, review, summaries, demo data) is described in
[`MEDICAL_REPORTS.md`](MEDICAL_REPORTS.md). Database changes for it are in Alembic revisions
`7a1c2e3d4f50`, `7a2b3c4d5e60` and `7b1a2c3d4e50` (report-date provenance:
`report.date_source`, `report.date_confirmed`, `report.detected_date`,
`reportextraction.date_candidates`). The backend creates missing tables at startup and logs an error
if existing tables lack model columns; run `alembic upgrade head` in that case (see
MEDICAL_REPORTS.md § 2).

## 5. Optional: deploy the vision worker on Modal

This step is only needed for `VISION_PROVIDER=cloud`; local operation does not use Modal.

The worker code is `backend/vision_worker/app.py`; the Modal app is `deploy/modal/holomed_vision.py`.

### What is deployed
- **App and function:** app `holomed-vision`, function `web` (ASGI), GPU `T4`.
- **Scaling:** scale to zero by default; `max_inputs=8` concurrent requests per container, with
  inference serialized by the model lock.
- **Image:** Debian slim with Python 3.12, torch 2.6.0 and torchvision 0.21.0 (CUDA 12.4 wheels),
  torchxrayvision 1.5.4, pydicom 3.0.2, pillow 12.3.0, numpy 2.4.6 and FastAPI 0.111.0.
- **Code shipped:** only `backend/config.py`, `backend/logger.py`, `backend/services/vision/`
  and `backend/vision_worker/`. No routers, tests, `.env` or weights. A test checks that every
  backend module the worker imports is shipped.
- **Weights:** the private Modal Volume `holomed-vision-weights`, mounted **read-only** at
  `/weights`.
- **Authentication:** every request needs `Authorization: Bearer <VISION_WORKER_TOKEN>`.
  Documentation endpoints are disabled.
- **Data handling:** images are processed in memory, not written to disk and not logged.
  Worker logs contain only format, target and timing.

### One-time setup
Run from the repository root. On Git Bash for Windows, prefix commands that take `/path`
arguments with `MSYS_NO_PATHCONV=1`.

```bash
.venv/Scripts/modal token new                      # browser login
modal volume create holomed-vision-weights
modal volume put holomed-vision-weights backend/models/weights/densenet121-res224-all.pt /densenet121-res224-all.pt
# Create a random token (do not echo it), write it to a temporary dotenv file as
# VISION_WORKER_TOKEN=<token>, then:
modal secret create holomed-vision-worker --from-dotenv <temporary-file>
# delete the temporary file; put the same token in the backend's VISION_CLOUD_TOKEN secret
```

### Deploy
```bash
modal deploy deploy/modal/holomed_vision.py
```
- **Billing:** GPU functions require a payment method on the Modal account.
- **Endpoint:** the command prints the endpoint URL. Set it as `VISION_CLOUD_URL` in the backend's
  secret environment, and set `VISION_PROVIDER=cloud` **only** in that environment.

### Verify
```bash
curl -s https://<host>/api/v1/vision/status      # expect provider "cloud" and status "ready"
```
Then run the browser workflow (upload, screen, select a finding, view Grad-CAM and the
explanation).

### Front-end routes (SPA history routing)

The workspace mirrors its page in the URL with the History API: `/imaging`, `/reports`,
`/reports/<id>`, `/clinical/<id>`, `/overview`, `/search`, `/timeline`, `/templates`,
`/privacy`, `/storage`, `/settings`. Browser Back/Forward, refresh and deep links therefore
work. **Any production web server must serve `index.html` for unknown paths** (`try_files $uri
/index.html` in nginx, or the equivalent), otherwise a refresh on `/reports/12` returns 404.
The Vite dev server already does this.

### OHIF viewer

The prebuilt viewer in `frontend/ohif` is served by FastAPI at `/ohif` and proxied by Vite.

- `frontend/ohif/app-config.js` must set `routerBasename: "/ohif/"`. With the default `"/"`
  the viewer mounts nothing and the page stays blank.
- The static mount falls back to `index.html` for extension-less paths, so `/ohif/viewer?...`
  and a refresh inside the viewer work.
- The viewer reads studies from the backend's DICOMweb endpoints
  (`/api/v1/dicomweb/...`): QIDO returns standard DICOM JSON when the client sends
  `Accept: application/dicom+json`, and WADO-RS frames are served as `multipart/related`
  (encapsulated frames keep their transfer syntax; uncompressed frames are sent as
  `application/octet-stream`). Every request is scoped to the signed-in owner's studies.
- The Imaging workspace embeds `${VITE_OHIF_URL or /ohif/}viewer?StudyInstanceUIDs=<uid>`.

## 6. Authentication

- **Password sign-in:** `POST /api/v1/auth/register` and `POST /api/v1/auth/login`. The login sets
  an HttpOnly `session` cookie containing an HS256 JWT (`sub` = user id).
- **Sign-out and session check:** `POST /api/v1/auth/logout` clears the cookie;
  `GET /api/v1/auth/me` returns the current user.
- **Google Sign-In:** optional. It uses the OpenID Connect authorization-code flow with PKCE,
  handled entirely by the backend.

### How Google Sign-In works
0. The frontend opens `/api/v1/auth/google?popup=1` in a **popup window** (the link flow uses
   `/api/v1/auth/google/link?popup=1`). Running the redirects in a popup keeps Google's pages out
   of the main window's session history, so the browser Back button stays inside HoloMed. The popup
   ends on `?auth_popup=1`, signals the opener (BroadcastChannel / same-origin postMessage) and
   closes; the main window then re-checks `GET /api/v1/auth/me` — **the signal itself carries no
   authority**. If the browser blocks popups, the classic full-page redirect is used instead. The
   popup mode is remembered in a short-lived HttpOnly cookie
   (`holomed_google_popup`, scoped to `/api/v1/auth/google`), so the callback knows where to
   send the result.
1. `GET /api/v1/auth/google` redirects to Google.
   - It requests only the `openid email profile` scopes, with `access_type=online`.
   - The request carries a random `state`, a nonce and a PKCE S256 challenge.
   - Those values are held only in a signed, HttpOnly, SameSite=Lax, 10-minute cookie scoped to
     `/api/v1/auth/google`. Each value is single-use.
2. `GET /api/v1/auth/google/callback` validates the `state` and exchanges the code, sending the
   client secret and the PKCE verifier.
3. The backend verifies the ID token with Google's `google-auth` library, which checks the
   signature, issuer, audience (the client ID), `iat` and `exp`. The backend then checks `nbf`,
   the nonce, `sub`, `email` and `email_verified`.
   - No Google access or refresh tokens are stored.
   - The callback's query string is redacted from access logs.
4. **Account mapping:** Google's stable `sub` is stored as `user.google_id`.
   - A known `sub` signs in to its account.
   - A new verified email creates a Google-only account.
   - An existing account with the same email but no Google link is **not** linked
     automatically. The user signs in with the password, then uses *Settings → Profile → Link
     Google account* (`GET /api/v1/auth/google/link`), which requires the same verified email.
   - A `sub` already linked to another account is rejected.
5. **Result:** success sets the same `session` cookie as password sign-in and redirects to
   `GOOGLE_POST_LOGIN_URL`. Any failure redirects there with `?auth_error=<code>`, a short code
   that never contains tokens, codes, state or secrets, and creates no user or session.

### Configuration
- **Client secret:** `GOOGLE_CLIENT_SECRET` is a backend secret. Never put it in the frontend or
  in `VITE_*` variables.
- **Local development redirect URI:** register exactly
  `http://localhost:5173/api/v1/auth/google/callback` in the Google Cloud OAuth *Web application*
  client. The Vite dev server proxies it to the backend.
  - Open the app at `http://localhost:5173`, not `127.0.0.1`, so the cookies match.
- **Production:** set these, then register the same `GOOGLE_REDIRECT_URI` in Google Cloud:
  - `GOOGLE_REDIRECT_URI=https://<your-host>/api/v1/auth/google/callback`
  - `GOOGLE_POST_LOGIN_URL=https://<your-host>/`
  - `HOLOMED_ENV=production` (Secure cookies)
  - `SESSION_COOKIE_SAMESITE=lax` if the frontend and API share a site, or `none` for a
    cross-site frontend (this forces Secure)
  - `CORS_ORIGINS=https://<your-frontend>`
- **Without Google configured:** the Google button returns the user to the sign-in screen with
  "Google sign-in is not configured".

## 7. Switching providers

| Goal | Setting |
|---|---|
| **Local GPU inference (primary; development/demo)** | `VISION_PROVIDER=local` (default) |
| Optional Modal GPU inference | `VISION_PROVIDER=cloud` + `VISION_CLOUD_URL` + `VISION_CLOUD_TOKEN` |
| **Local text explanations (primary)** | `TEXT_AI_PROVIDER=ollama` (default) |
| Optional hosted text explanations | `TEXT_AI_PROVIDER=omniroute` + `OMNIROUTE_*` |

### What the UI shows
The screening workspace shows the active provider from `GET /api/v1/vision/status`:

| Mode | Badge | Model Information |
|---|---|---|
| Local | **Local GPU** (or **Local CPU**) | Provider, the detected device name reported by the model service (for example the NVIDIA GPU name, never hardcoded), and model DenseNet-121 |
| Cloud | **Managed GPU** | Provider and model; no worker URL, token or infrastructure details |

The status endpoint returns only
`provider`, `provider_configured`, `model_ready`, `accelerator` (`gpu`/`cpu`) and `status`.

- **Frontend:** unchanged in every case.
- **Misconfiguration:** an unknown or unconfigured provider returns `503`. Nothing falls back
  silently to another provider.

## 8. Cold start and performance

| Setup | Measurement |
|---|---|
| Local (RTX 3070 Ti) | Model load about 0.35 s (0.9 s with warm-up). The first request after `VISION_PRELOAD=1` completed in about 0.25 s in the browser. Warm HTTP median 99.8 ms (NIH PNG) and 184.7 ms (SIIM DICOM). See `docs/VISION_SERVICE.md` §13. |
| Local explanations (qwen3:8b) | About 5–6 s median per finding. The first call after Ollama starts can take about 60 s while the model loads. |
| Modal (T4) | **Not measured yet.** With scale to zero, the first request after idle includes container start, weight load and warm-up; the worker preloads at container start. The observed numbers will be recorded here. |

## 9. Limitations
- **Not clinically validated:** a research/hackathon demonstration only. Scores are uncalibrated
  model outputs, and Grad-CAM is not evidence of disease.
- **Throughput:** one Grad-CAM at a time per process (model lock).
- **Short-lived results:** structured results used for explanations live in process memory
  (default 30 min). They are lost on restart and not shared across multiple backend instances.
- **Explanation fallback:** explanations depend on a text AI service. When it is unavailable,
  screening still works and the UI shows "AI explanation unavailable".
- **OmniRoute:** implemented and contract-tested, but not deployed or tested live.
- **Modal:** see the status at the top of this document.
- **No compliance claims:** HIPAA, GDPR and DPDP compliance are not claimed. Data retention depends
  on the actual hosting configuration.
- **Data licensing:** the NIH ChestX-ray14 sample is included with attribution
  (`backend/tests/artifacts/real_cxr/ATTRIBUTION.md`). SIIM-ACR files are excluded pending
  licensing review.
