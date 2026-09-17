"""Modal deployment of the HoloMed private vision worker.

Runs backend/vision_worker (the exact validated TorchXRayVision DenseNet-121 +
Grad-CAM pipeline) on a GPU. The browser never calls this service; only the
HoloMed API does, with a bearer token.

One-time setup (see docs/DEPLOYMENT.md):
  modal volume create holomed-vision-weights
  modal volume put holomed-vision-weights backend/models/weights/densenet121-res224-all.pt /densenet121-res224-all.pt
  modal secret create holomed-vision-worker --from-dotenv <file with VISION_WORKER_TOKEN=...>
Deploy:
  modal deploy deploy/modal/holomed_vision.py

Weights live in a private Modal Volume mounted read-only; the service verifies
SHA-256 56524913dd16...8899 before loading and refuses anything else.
"""
import os
from pathlib import Path

import modal

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "holomed-vision"
WEIGHTS_MOUNT = "/weights"

# Only the modules the worker needs are shipped into the image.
_ALLOWED = (
    "__init__.py",
    "config.py",
    "services/__init__.py",
    "services/vision/",
    "vision_worker/",
)


def _ignore(path: Path) -> bool:
    rel = path.as_posix()
    if "__pycache__" in rel or path.suffix in (".pyc", ".pt", ".db"):
        return True
    return not any(rel == a or rel.startswith(a) or a.startswith(rel + "/") for a in _ALLOWED)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.6.0",
        "torchvision==0.21.0",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    .pip_install(
        "torchxrayvision==1.5.4",
        "pydicom==3.0.2",
        "pillow==12.3.0",
        "numpy==2.4.6",
        "scikit-image==0.26.0",
        "pandas==3.0.5",
        "fastapi==0.111.0",
        "python-multipart==0.0.32",
        "python-dotenv==1.0.1",
        "pydantic==2.12.0",
        "httpx==0.27.0",
    )
    .env({
        "VISION_WEIGHTS_PATH": f"{WEIGHTS_MOUNT}/densenet121-res224-all.pt",
        "VISION_DEVICE": "cuda",
        "VISION_PRELOAD": "1",
        "VISION_PROVIDER": "local",
        "PYTHONUNBUFFERED": "1",
    })
    .add_local_dir(REPO_ROOT / "backend", "/root/backend", ignore=_ignore)
)

weights = modal.Volume.from_name("holomed-vision-weights")
app = modal.App(APP_NAME)


@app.function(
    image=image,
    gpu=os.environ.get("HOLOMED_MODAL_GPU", "T4"),
    volumes={WEIGHTS_MOUNT: weights.read_only()},
    secrets=[modal.Secret.from_name("holomed-vision-worker", required_keys=["VISION_WORKER_TOKEN"])],
    min_containers=int(os.environ.get("HOLOMED_MODAL_MIN_CONTAINERS", "0")),
    scaledown_window=int(os.environ.get("HOLOMED_MODAL_SCALEDOWN_SECONDS", "600")),
    timeout=180,
)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def web():
    from backend.vision_worker.app import create_app
    return create_app()
