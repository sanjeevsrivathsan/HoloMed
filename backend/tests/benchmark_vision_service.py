"""HoloMed vision service — baseline benchmark (Phase 3).

Measures the service as deployed in-process: model load (once), the first request,
and repeated requests through ``inference.screen_image`` and through the
``/api/v1/vision/screen`` route handler (audit log included; FastAPI's HTTP layer
excluded, see docs/VISION_SERVICE.md). Results: artifacts/vision_service_benchmark.json

Run from the project root:
  PYTHONIOENCODING=utf-8 JWT_SECRET=testsecret python backend/tests/benchmark_vision_service.py
"""
import asyncio
import json
import os
import platform
import sys
import tempfile
import time
import warnings

import numpy as np
import torch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
warnings.simplefilter("ignore")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402
from starlette.datastructures import Headers, UploadFile  # noqa: E402

from backend.models import User  # noqa: E402
from backend.routers import vision as vision_router  # noqa: E402
from backend.services.vision import inference, model  # noqa: E402

HERE = os.path.dirname(__file__)
SOURCE = os.path.join(HERE, "artifacts", "real_cxr", "source")
SAMPLES = {
    "nih_png": os.path.join(SOURCE, "00000001_000.png"),
    "siim_dicom": os.path.join(SOURCE, "1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm"),
}
N = 50


def summarize(values):
    a = np.asarray(values, dtype=float)
    return {"n": int(a.size), "median_ms": round(float(np.median(a)), 3),
            "p95_ms": round(float(np.percentile(a, 95)), 3),
            "mean_ms": round(float(a.mean()), 3), "max_ms": round(float(a.max()), 3)}


def main():
    cuda = torch.cuda.is_available()
    t0 = time.perf_counter()
    vm = model.get_vision_model()
    load_total_ms = (time.perf_counter() - t0) * 1000
    report = {
        "system": {"python": platform.python_version(), "torch": torch.__version__,
                   "device": vm.device_name, "cpu": platform.processor()},
        "model_load": {"hash_and_deserialize_ms": round(vm.load_ms, 3),
                       "including_warm_up_ms": round(load_total_ms, 3)},
        "samples": {},
    }
    if cuda:
        torch.cuda.reset_peak_memory_stats(vm.device)
        report["gpu_memory_after_load_mb"] = round(torch.cuda.memory_allocated(vm.device) / 1024 ** 2, 2)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        user = User(email="bench@example.com", hashed_password="x")
        s.add(user)
        s.commit()
        s.refresh(user)

    async def to_thread(func, *args):
        return await asyncio.to_thread(func, *args)

    vision_router.run_in_threadpool = to_thread  # anyio is unavailable in this environment

    def handler_call(data, name):
        spool = tempfile.SpooledTemporaryFile(max_size=1 << 30)
        spool.write(data)
        spool.seek(0)
        upload = UploadFile(file=spool, filename=name, headers=Headers({"content-type": "application/octet-stream"}))

        async def run():
            with Session(engine) as session:
                return await vision_router.screen(file=upload, target=None, user=user, session=session)
        return asyncio.run(run())

    for key, path in SAMPLES.items():
        with open(path, "rb") as f:
            data = f.read()
        first = inference.screen_image(data)
        timings = {k: [] for k in ("preprocessing_ms", "inference_ms", "gradcam_ms", "rendering_ms", "total_ms")}
        for _ in range(N):
            r = inference.screen_image(data)
            for k in timings:
                timings[k].append(getattr(r.timing, k))
        handler_ms = []
        for _ in range(N):
            t = time.perf_counter()
            r = handler_call(data, os.path.basename(path))
            handler_ms.append((time.perf_counter() - t) * 1000)
        report["samples"][key] = {
            "primary_finding": {"pathology": r.primary_finding.pathology, "score": r.primary_finding.score},
            "first_request_timing": first.timing.model_dump(),
            "service": {k: summarize(v) for k, v in timings.items()},
            "route_handler_wall": summarize(handler_ms),
            "response_json_kb": round(len(r.model_dump_json()) / 1024, 1),
        }
    if cuda:
        report["gpu_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated(vm.device) / 1024 ** 2, 2)
        report["gpu_peak_reserved_mb"] = round(torch.cuda.max_memory_reserved(vm.device) / 1024 ** 2, 2)
    out = os.path.join(HERE, "artifacts", "vision_service_benchmark.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
