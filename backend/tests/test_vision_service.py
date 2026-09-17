"""Tests for the vision AI service (backend/services/vision) and /api/v1/vision/screen.

Uses the local validated checkpoint and the Phase 2 real CXR samples; no network.
API tests drive the ASGI app directly (no httpx) so they also run where the
``ssl`` module cannot be loaded; a full-app TestClient test runs where it can.
"""
import asyncio
import base64
import copy
import io
import json
import os
import re
import subprocess
import sys
import threading
import time

import numpy as np
import pydicom
import pytest
import torch
from fastapi import FastAPI
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import config
from backend.database import get_session
from backend.dependencies.auth import get_current_user
from backend.models import AuditLog, User
from backend.routers import vision as vision_router
from backend.services.vision import explainability, inference, model, preprocessing
from backend.services.vision.schemas import SAFETY_MESSAGE, VisionScreenResponse

HERE = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SOURCE_DIR = os.path.join(HERE, "artifacts", "real_cxr", "source")
NIH_PNG = os.path.join(SOURCE_DIR, "00000001_000.png")
SIIM_DCM = os.path.join(SOURCE_DIR, "1.2.276.0.7230010.3.1.4.8323329.6904.1517875201.850819.dcm")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(config.VISION_WEIGHTS_PATH),
    reason="validated local vision checkpoint not present",
)
needs_samples = pytest.mark.skipif(
    not (os.path.isfile(NIH_PNG) and os.path.isfile(SIIM_DCM)),
    reason="Phase 2 real CXR samples not present",
)


# ── helpers ───────────────────────────────────────────────────────────────
def read(path):
    with open(path, "rb") as f:
        return f.read()


def png_bytes(arr, mode=None):
    buf = io.BytesIO()
    Image.fromarray(arr, mode=mode).save(buf, format="PNG") if mode else Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def make_dicom(pixels, photometric="MONOCHROME2", modality="DX", bits_stored=12,
               samples=1, frames=None, extra=None):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientName = "Sensitive^Name"
    ds.PatientID = "SENSITIVE-ID-4242"
    ds.InstitutionName = "Sensitive Hospital"
    if modality is not None:
        ds.Modality = modality
    ds.PhotometricInterpretation = photometric
    ds.SamplesPerPixel = samples
    ds.Rows, ds.Columns = pixels.shape[-2] if samples == 1 else pixels.shape[0], \
        pixels.shape[-1] if samples == 1 else pixels.shape[1]
    ds.BitsAllocated = 16 if bits_stored > 8 else 8
    ds.BitsStored = bits_stored
    ds.HighBit = bits_stored - 1
    ds.PixelRepresentation = 0
    if samples == 3:
        ds.PlanarConfiguration = 0
    if frames:
        ds.NumberOfFrames = frames
    for k, v in (extra or {}).items():
        setattr(ds, k, v)
    dtype = np.uint16 if ds.BitsAllocated == 16 else np.uint8
    ds.PixelData = pixels.astype(dtype).tobytes()
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def ramp_image(h=256, w=256, maxval=4095):
    y, x = np.mgrid[0:h, 0:w]
    return ((x + y) / (h + w - 2) * maxval).round()


def multipart(fields):
    boundary = "holomed-test-boundary-7d1f"
    body = b""
    for name, filename, content, ctype in fields:
        disp = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        head = f"--{boundary}\r\nContent-Disposition: {disp}\r\n"
        if ctype:
            head += f"Content-Type: {ctype}\r\n"
        body += head.encode() + b"\r\n" + content + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def asgi_post(app, path, fields):
    body, ctype = multipart(fields)

    async def run():
        messages, sent = [], False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": b"", "root_path": "",
            "headers": [(b"content-type", ctype.encode()),
                        (b"content-length", str(len(body)).encode()),
                        (b"host", b"testserver")],
            "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        }
        await app(scope, receive, send)
        return messages

    messages = asyncio.run(run())
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return status, json.loads(raw), raw


# ── fixtures ──────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def vm():
    return model.get_vision_model()


@pytest.fixture(scope="module")
def nih_pre():
    if not os.path.isfile(NIH_PNG):
        pytest.skip("NIH sample not present")
    return preprocessing.preprocess(read(NIH_PNG))


@pytest.fixture(name="api")
def api_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        user = User(email="vision@example.com", hashed_password="x")
        s.add(user)
        s.commit()
        s.refresh(user)
        user_snapshot = copy.copy(user)

    def session_override():
        with Session(engine) as s:
            yield s

    app = FastAPI()
    app.include_router(vision_router.router)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_user] = lambda: user_snapshot
    yield app, engine
    SQLModel.metadata.drop_all(engine)


# ── 1-3, 18, 20: model ────────────────────────────────────────────────────
def test_model_loads_on_expected_device(vm):
    expected = "cuda" if torch.cuda.is_available() else "cpu"
    assert vm.device.type == expected
    assert next(vm.module.parameters()).device.type == expected
    assert not vm.module.training
    assert vm.load_ms > 0


def test_weight_hash_verified(vm):
    assert vm.weight_sha256 == model.EXPECTED_SHA256
    assert model.sha256_file(config.VISION_WEIGHTS_PATH) == model.EXPECTED_SHA256


def test_altered_or_missing_checkpoint_is_rejected(tmp_path):
    bad = tmp_path / "densenet121-res224-all.pt"
    bad.write_bytes(b"not the validated checkpoint")
    with pytest.raises(model.VisionModelError, match="SHA-256"):
        model.load_model(weights_path=str(bad), device="cpu")
    with pytest.raises(model.VisionModelError, match="not available"):
        model.load_model(weights_path=str(tmp_path / "missing.pt"), device="cpu")


def test_eighteen_targets(vm, nih_pre):
    assert vm.targets == model.EXPECTED_TARGETS
    assert len(vm.targets) == 18
    with torch.no_grad():
        out = vm.module(nih_pre.tensor.to(vm.device))
    assert tuple(out.shape) == (1, 18)


def test_matches_torchxrayvision_constructor_when_cached(vm, nih_pre):
    """Local loading must equal xrv.models.DenseNet(weights=...) (no download attempted)."""
    import torchxrayvision as xrv
    url = xrv.models.model_urls[model.WEIGHTS_ID]["weights_url"]
    cached = os.path.join(os.path.expanduser(xrv.utils.get_cache_dir()), os.path.basename(url))
    if not os.path.isfile(cached):
        pytest.skip("xrv cache copy not present; skipping to avoid a download")
    ref = xrv.models.DenseNet(weights=model.WEIGHTS_ID).cpu().eval()
    local = model.load_model(device="cpu").module
    x = nih_pre.tensor
    with torch.no_grad():
        assert torch.equal(ref(x), local(x))
    assert torch.equal(ref.op_threshs, local.op_threshs)
    assert ref.input_resolution == local.input_resolution


def test_singleton_loads_once(monkeypatch, vm):
    assert model.get_vision_model() is vm
    calls = []
    monkeypatch.setattr(model, "_instance", None)
    monkeypatch.setattr(model, "load_model", lambda: calls.append(1) or vm)
    threads = [threading.Thread(target=model.get_vision_model) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert model.get_vision_model() is vm
    assert calls == [1]


def test_cpu_fallback(monkeypatch, vm, nih_pre):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert model.resolve_device("auto").type == "cpu"
    with pytest.raises(model.VisionModelError):
        model.resolve_device("cuda")
    monkeypatch.undo()
    cpu_vm = model.load_model(device="cpu")
    assert cpu_vm.device.type == "cpu"
    cpu_scores = inference.model_scores(cpu_vm, nih_pre.tensor)
    ref = inference.model_scores(vm, nih_pre.tensor.to(vm.device))
    for p in model.EXPECTED_TARGETS:
        assert cpu_scores[p] == pytest.approx(ref[p], abs=1e-3)  # CPU vs CUDA kernels
    cam = explainability.grad_cam(cpu_vm.module, nih_pre.tensor, 10)
    assert cam.cam.shape == (224, 224) and cam.gradient_norm > 0


# ── 4-9: preprocessing ────────────────────────────────────────────────────
@needs_samples
def test_png_preprocessing_matches_phase2(nih_pre):
    sys.path.insert(0, HERE)
    import validate_real_cxr as p2
    arr, maxval, _ = p2.load_png(NIH_PNG)
    ref, crop = p2.preprocess(arr, maxval)
    assert torch.equal(nih_pre.tensor, ref)
    assert nih_pre.crop == crop
    assert nih_pre.decoded.format == "png" and nih_pre.decoded.maxval == 255
    assert np.array_equal(nih_pre.display, np.asarray(Image.open(NIH_PNG)))


@needs_samples
def test_dicom_preprocessing_matches_phase2():
    sys.path.insert(0, HERE)
    import validate_real_cxr as p2
    pre = preprocessing.preprocess(read(SIIM_DCM))
    arr, maxval, _ = p2.load_dicom(SIIM_DCM)
    ref, crop = p2.preprocess(arr, maxval)
    assert torch.equal(pre.tensor, ref)
    assert pre.crop == crop
    d = pre.decoded
    assert (d.format, d.modality, d.source_mode, d.bits_stored) == ("dicom", "CR", "MONOCHROME2", 8)


@needs_samples
def test_jpeg_and_rgb_inputs_are_converted_to_grayscale():
    img = Image.open(NIH_PNG)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    pre = preprocessing.preprocess(buf.getvalue())
    assert pre.decoded.format == "jpeg" and tuple(pre.tensor.shape) == (1, 1, 224, 224)
    rgb = io.BytesIO()
    img.convert("RGB").save(rgb, format="PNG")
    pre_rgb = preprocessing.preprocess(rgb.getvalue())
    assert pre_rgb.decoded.source_mode == "RGB"
    assert any("RGB -> L" in s for s in pre_rgb.steps)
    assert torch.allclose(pre_rgb.tensor, preprocessing.preprocess(read(NIH_PNG)).tensor)


def test_sixteen_bit_png_uses_16_bit_maxval():
    arr = ramp_image(128, 128, 65535).astype(np.uint16)
    pre = preprocessing.preprocess(png_bytes(arr))
    assert pre.decoded.maxval == 65535
    assert pre.tensor.min() >= -1024.001 and pre.tensor.max() <= 1024.001


def test_non_square_input_is_center_cropped():
    arr = np.zeros((300, 200), dtype=np.uint8)
    arr[:, :] = 128
    pre = preprocessing.preprocess(png_bytes(arr))
    assert pre.crop == (50, 0, 200)
    assert tuple(pre.tensor.shape) == (1, 1, 224, 224)


def test_dicom_monochrome1_is_inverted():
    px = ramp_image()
    m2 = preprocessing.preprocess(make_dicom(px, "MONOCHROME2"))
    m1 = preprocessing.preprocess(make_dicom(4095 - px, "MONOCHROME1"))
    assert any("MONOCHROME1 inverted" in s for s in m1.steps)
    assert torch.allclose(m1.tensor, m2.tensor)


def test_dicom_rescale_and_voi_window_are_applied():
    px = ramp_image()
    pre = preprocessing.preprocess(make_dicom(px, extra={
        "RescaleSlope": "1", "RescaleIntercept": "0",
        "WindowCenter": "2048", "WindowWidth": "1024"}))
    assert any("Modality LUT" in s for s in pre.steps)
    assert any("VOI LUT" in s for s in pre.steps)
    assert pre.decoded.maxval == 255
    assert pre.decoded.pixels.min() == 0 and pre.decoded.pixels.max() == pytest.approx(255)
    # windowing saturates the extremes of the ramp
    assert (pre.decoded.pixels == 0).mean() > 0.2


def test_tensor_shape_and_finite(nih_pre):
    t = nih_pre.tensor
    assert tuple(t.shape) == (1, 1, 224, 224) and t.dtype == torch.float32
    assert torch.isfinite(t).all()
    assert t.min() >= -1024.001 and t.max() <= 1024.001


def test_malformed_inputs_raise_invalid():
    good = png_bytes(np.full((128, 128), 100, dtype=np.uint8))
    for data in (b"", good[:40], b"\xff\xd8\xff" + b"\x00" * 50):
        with pytest.raises(preprocessing.InvalidImageError):
            preprocessing.preprocess(data)
    # A DICOM preamble followed by junk is rejected (parse failure or no pixel data).
    with pytest.raises((preprocessing.InvalidImageError, preprocessing.UnsupportedImageError)):
        preprocessing.preprocess(b"\0" * 128 + b"DICM" + b"\x02\x00\x10\x00garbage")


def test_truncated_dicom_pixel_data_is_invalid():
    data = make_dicom(ramp_image())
    with pytest.raises((preprocessing.InvalidImageError, preprocessing.UnsupportedImageError)):
        preprocessing.preprocess(data[:-5000])


def test_unsupported_inputs():
    gif = io.BytesIO()
    Image.new("L", (100, 100)).save(gif, format="GIF")
    for data in (b"plain text, not an image", gif.getvalue(), b"%PDF-1.7 ..."):
        with pytest.raises(preprocessing.UnsupportedImageError) as exc:
            preprocessing.preprocess(data)
        assert exc.value.media_type
    px = ramp_image()
    cases = [
        make_dicom(px, modality="CT"),
        make_dicom(np.zeros((64, 64, 3)), photometric="RGB", samples=3, bits_stored=8),
        make_dicom(np.zeros((2, 64, 64)), frames=2),
        make_dicom(np.zeros((16, 16))),
        png_bytes(np.zeros((16, 16), dtype=np.uint8)),
    ]
    for data in cases:
        with pytest.raises(preprocessing.UnsupportedImageError) as exc:
            preprocessing.preprocess(data)
        assert not exc.value.media_type


def test_dicom_without_modality_is_accepted():
    pre = preprocessing.preprocess(make_dicom(ramp_image(), modality=None))
    assert pre.decoded.modality is None


# ── 9-15: inference and Grad-CAM ──────────────────────────────────────────
def test_scores_finite_and_in_range(vm, nih_pre):
    scores = inference.model_scores(vm, nih_pre.tensor.to(vm.device))
    assert list(scores) == model.EXPECTED_TARGETS
    assert all(np.isfinite(v) and 0.0 <= v <= 1.0 for v in scores.values())


def test_no_second_sigmoid(vm, nih_pre):
    """Scores equal sigmoid+op_norm of the classifier logits, applied exactly once."""
    import torchxrayvision as xrv
    x = nih_pre.tensor.to(vm.device)
    scores = inference.model_scores(vm, x)
    with torch.no_grad():
        logits = vm.module.classifier(vm.module.features2(x))
        expected = xrv.models.op_norm(torch.sigmoid(logits), vm.module.op_threshs)[0].cpu()
        double = torch.sigmoid(expected)
    got = torch.tensor([scores[p] for p in vm.targets])
    assert torch.allclose(got, expected, atol=1e-6)
    assert not torch.allclose(got, double, atol=1e-3)
    assert got.min() < 0.5  # a double sigmoid can never go below 0.5
    if os.path.isfile(NIH_PNG):
        # Phase 2 reference value for NIH 00000001_000.png
        assert scores["Cardiomegaly"] == pytest.approx(0.6600, abs=1e-3)


def test_primary_finding_selection():
    targets = ["A", "B", "C"]
    assert inference.select_target({"A": 0.2, "B": 0.9, "C": 0.5}, targets, None) == 1
    assert inference.select_target({"A": 0.7, "B": 0.7, "C": 0.1}, targets, None) == 0
    assert inference.select_target({"A": 0.2, "B": 0.9, "C": 0.5}, targets, "C") == 2
    with pytest.raises(inference.UnknownTargetError):
        inference.select_target({"A": 0.2, "B": 0.9, "C": 0.5}, targets, "Abnormality")


def test_gradcam_generation_and_target(vm, nih_pre):
    x = nih_pre.tensor.to(vm.device)
    scores = inference.model_scores(vm, x)
    idx = inference.select_target(scores, vm.targets, None)
    with vm.lock:
        cam = explainability.grad_cam(vm.module, x, idx)
        low = explainability.grad_cam(vm.module, x, int(np.argmin([scores[p] for p in vm.targets])))
    assert vm.targets[idx] == "Cardiomegaly" if os.path.isfile(NIH_PNG) else True
    assert cam.target_index == idx
    assert cam.target_score == pytest.approx(scores[vm.targets[idx]], abs=1e-4)
    assert cam.activation_shape == (1, 1024, 7, 7)
    assert explainability.TARGET_LAYER == "features.denseblock4"
    assert np.corrcoef(cam.cam.ravel(), low.cam.ravel())[0, 1] < 0.99  # class-specific
    layer = explainability.target_layer(vm.module)
    assert not layer._forward_hooks and not layer._backward_hooks
    assert all(p.grad is None for p in vm.module.parameters())
    with pytest.raises(ValueError):
        explainability.grad_cam(vm.module, x, 18)


def test_heatmap_dimensions_finite_nonzero(vm, nih_pre):
    x = nih_pre.tensor.to(vm.device)
    with vm.lock:
        cam = explainability.grad_cam(vm.module, x, 10)
    assert cam.cam.shape == (224, 224)
    assert np.isfinite(cam.cam).all()
    assert cam.gradient_norm > 0 and cam.cam_raw_max > 0
    assert cam.cam.min() == 0.0 and cam.cam.max() == pytest.approx(1.0)
    assert 0.01 < (cam.cam > 0.2).mean() < 0.99
    original = explainability.render_original(nih_pre.display, nih_pre.crop, 256)
    assert original.shape == (256, 256) and original.dtype == np.uint8
    overlay = explainability.render_overlay(original, cam.cam)
    assert overlay.shape == (256, 256, 3) and overlay.dtype == np.uint8
    full = explainability.render_original(nih_pre.display, nih_pre.crop, 4096)
    assert np.array_equal(full, nih_pre.display)  # square 512 input: crop is the whole image
    heat = explainability.apply_jet_colormap(cam.cam)
    assert heat.shape == (224, 224, 3)


# ── 16-17, 19: service response, safety, concurrency ─────────────────────
BANNED = [r"\bdiagnosed\b", r"\bconfirmed\b", r"\bdefinitely\b", r"\bpatient has\b",
          r"\bsafe\b", r"\bclinically proven\b"]


def assert_safe_language(text):
    lowered = text.lower()
    for pattern in BANNED:
        assert not re.search(pattern, lowered), pattern


@needs_samples
def test_screen_image_response_and_safety(vm):
    r = inference.screen_image(read(NIH_PNG), vm=vm)
    assert isinstance(r, VisionScreenResponse)
    assert r.safety.message == SAFETY_MESSAGE
    assert r.safety.message == ("AI-generated screening assistance — not a diagnostic determination. "
                                "Consult a qualified healthcare professional.")
    assert r.safety.requires_clinical_review is True
    assert len(r.findings) == 18
    assert [f.score for f in r.findings] == sorted((f.score for f in r.findings), reverse=True)
    assert r.primary_finding == r.findings[0]
    assert r.explanation.target_pathology == r.primary_finding.pathology == "Cardiomegaly"
    assert r.explanation.target_layer == "features.denseblock4"
    assert "not proof" in r.explanation.description
    assert r.model.weight_sha256 == model.EXPECTED_SHA256 and r.model.targets == 18
    heat = Image.open(io.BytesIO(base64.b64decode(r.explanation.heatmap.data)))
    assert heat.size == (224, 224) == (r.explanation.heatmap.width, r.explanation.heatmap.height)
    overlay = Image.open(io.BytesIO(base64.b64decode(r.explanation.overlay.data)))
    assert overlay.size == (512, 512)
    original = Image.open(io.BytesIO(base64.b64decode(r.explanation.original.data)))
    assert original.mode == "L" and original.size == (512, 512)
    assert np.array_equal(np.asarray(original), np.asarray(Image.open(NIH_PNG)))
    assert all(v >= 0 for v in r.timing.model_dump().values())
    assert r.inferred_at.tzinfo is not None
    assert_safe_language(r.model_dump_json())


@needs_samples
def test_screen_image_requested_target(vm):
    r = inference.screen_image(read(NIH_PNG), target="Effusion", vm=vm)
    assert r.explanation.target_pathology == "Effusion"
    assert r.primary_finding.pathology == "Cardiomegaly"
    with pytest.raises(inference.UnknownTargetError):
        inference.screen_image(read(NIH_PNG), target="Abnormal", vm=vm)


def test_overlay_is_downscaled_to_configured_limit(vm, monkeypatch):
    monkeypatch.setattr(config, "VISION_MAX_OVERLAY_SIDE", 128)
    r = inference.screen_image(make_dicom(ramp_image(300, 300)), vm=vm)
    assert (r.explanation.overlay.width, r.explanation.overlay.height) == (128, 128)
    assert (r.explanation.original.width, r.explanation.original.height) == (128, 128)


@needs_samples
def test_lock_serializes_model_use(vm, monkeypatch):
    active, peak, lock_held = [0], [0], []
    guard = threading.Lock()
    real_grad_cam = explainability.grad_cam

    def tracked(module, x, idx):
        lock_held.append(vm.lock.locked())
        with guard:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.02)
        try:
            return real_grad_cam(module, x, idx)
        finally:
            with guard:
                active[0] -= 1

    monkeypatch.setattr(explainability, "grad_cam", tracked)
    data = [read(NIH_PNG), read(SIIM_DCM)] * 3
    expected = {d: inference.screen_image(d, vm=vm) for d in data[:2]}
    results, errors = [], []

    def worker(d):
        try:
            results.append((d, inference.screen_image(d, vm=vm)))
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(d,)) for d in data]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(results) == len(data)
    assert peak[0] == 1
    assert all(lock_held)
    for d, r in results:
        ref = expected[d]
        assert r.explanation.target_pathology == ref.explanation.target_pathology
        for got, want in zip(r.findings, ref.findings):
            assert got.pathology == want.pathology
            assert got.score == pytest.approx(want.score, abs=1e-5)


# ── 17: API ───────────────────────────────────────────────────────────────
def test_router_import_does_not_import_torch():
    code = "import sys, backend.routers.vision; print('torch' in sys.modules)"
    env = dict(os.environ, JWT_SECRET="testsecret")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def _anyio_asyncio_available():
    try:
        import anyio._backends._asyncio  # noqa: F401  (imports ssl)
        return True
    except ImportError:
        return False


ANYIO_OK = _anyio_asyncio_available()


def _direct_post(app_engine_user, monkeypatch, fields):
    """Call the route handler directly (no anyio): multipart parsing is replaced by
    building the handler arguments; run_in_threadpool is replaced by asyncio.to_thread."""
    import tempfile
    from fastapi import HTTPException
    from starlette.datastructures import Headers, UploadFile

    _, engine, user = app_engine_user

    async def to_thread(func, *args):
        return await asyncio.to_thread(func, *args)

    monkeypatch.setattr(vision_router, "run_in_threadpool", to_thread)
    file_field = next((f for f in fields if f[0] == "file"), None)
    target = next((f[2].decode() for f in fields if f[0] == "target"), None)
    if file_field is None:
        return 422, {"detail": "file is required"}, b""
    spool = tempfile.SpooledTemporaryFile(max_size=1 << 30)
    spool.write(file_field[2])
    spool.seek(0)
    upload = UploadFile(file=spool, filename=file_field[1],
                        headers=Headers({"content-type": file_field[3] or "application/octet-stream"}))

    async def run():
        with Session(engine) as session:
            return await vision_router.screen(file=upload, target=target, user=user, session=session)

    try:
        result = asyncio.run(run())
    except HTTPException as exc:
        raw = json.dumps({"detail": exc.detail}).encode()
        return exc.status_code, json.loads(raw), raw
    raw = VisionScreenResponse.model_validate(result).model_dump_json().encode()
    return 200, json.loads(raw), raw


@pytest.fixture(params=["direct", "asgi"])
def post(request, api, monkeypatch):
    """POST /api/v1/vision/screen, either through the handler or through ASGI."""
    app, engine = api
    if request.param == "asgi":
        if not ANYIO_OK:
            pytest.skip("anyio asyncio backend unavailable: the ssl module is blocked in this environment")
        return lambda fields: asgi_post(app, "/api/v1/vision/screen", fields)
    user = app.dependency_overrides[get_current_user]()
    return lambda fields: _direct_post((app, engine, user), monkeypatch, fields)


@needs_samples
def test_api_png_and_dicom(api, post, vm, monkeypatch):
    _, engine = api
    import backend.services.storage as storage
    monkeypatch.setattr(storage, "store_file",
                        lambda *a, **k: pytest.fail("vision uploads must not be stored"))
    for path, fmt, ctype in ((NIH_PNG, "png", "image/png"), (SIIM_DCM, "dicom", "application/dicom")):
        status, body, raw = post([("file", os.path.basename(path), read(path), ctype)])
        assert status == 200, body
        parsed = VisionScreenResponse.model_validate(body)
        assert parsed.input.format == fmt
        assert len(parsed.findings) == 18
        assert body["safety"]["message"] == SAFETY_MESSAGE
        assert body["explanation"]["target_layer"] == "features.denseblock4"
        text = raw.decode()
        assert_safe_language(text)
        assert os.path.basename(path) not in text
        for fragment in ("real_cxr", "artifacts", "weights/", ".pt\"", "\\\\", "I:/", "C:/"):
            assert fragment not in text, fragment
    with Session(engine) as s:
        logs = s.exec(select(AuditLog).where(AuditLog.action == "vision_screen")).all()
    assert len(logs) == 2
    assert json.loads(logs[1].details) == {"input_format": "dicom",
                                           "weights": "densenet121-res224-all",
                                           "target_pathology": "Mass"}


def test_api_does_not_expose_sensitive_dicom_metadata(post, vm):
    status, body, raw = post([("file", "C:/private/path/scan.dcm", make_dicom(ramp_image()), None)])
    assert status == 200, body
    text = raw.decode()
    for secret in ("Sensitive", "SENSITIVE-ID-4242", "private/path", "scan.dcm"):
        assert secret not in text
    assert set(body["input"]) == {"format", "width", "height", "source_mode", "bits_stored",
                                  "modality", "transfer_syntax", "preprocessing"}


def test_api_error_handling(post, vm, monkeypatch):
    status, body, _ = post([("file", "a.txt", b"hello world", "text/plain")])
    assert status == 415
    status, _, _ = post([("file", "a.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 20, "image/png")])
    assert status == 400
    status, _, _ = post([("file", "a.png", b"", "image/png")])
    assert status == 400
    status, body, _ = post([("file", "ct.dcm", make_dicom(ramp_image(), modality="CT"), None)])
    assert status == 422 and "modality" in body["detail"]
    good = make_dicom(ramp_image())
    status, body, _ = post([("file", "x.dcm", good, None), ("target", None, b"Abnormality", None)])
    assert status == 422
    status, body, _ = post([("file", "x.dcm", good, None), ("target", None, b"Edema", None)])
    assert status == 200 and body["explanation"]["target_pathology"] == "Edema"
    status, _, _ = post([])
    assert status == 422
    monkeypatch.setattr(config, "VISION_MAX_UPLOAD_BYTES", 1024)
    status, body, _ = post([("file", "x.dcm", good, None)])
    assert status == 413


def test_api_model_unavailable_returns_503(post, monkeypatch):
    def unavailable():
        raise model.VisionModelError("Vision model checkpoint failed SHA-256 verification")

    monkeypatch.setattr(inference, "get_vision_model", unavailable)
    status, body, raw = post([("file", "x.dcm", make_dicom(ramp_image()), None)])
    assert status == 503
    assert body["detail"] == "Vision model is not available"
    assert b"SHA-256" not in raw


def test_provider_selection(monkeypatch):
    from backend.services.vision import provider
    monkeypatch.setattr(config, "VISION_PROVIDER", "local")
    assert isinstance(provider.get_vision_provider(), provider.LocalVisionProvider)
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    with pytest.raises(provider.VisionProviderUnavailable):
        provider.get_vision_provider().screen(b"x")
    monkeypatch.setattr(config, "VISION_PROVIDER", "replicate")
    with pytest.raises(provider.VisionProviderUnavailable):
        provider.get_vision_provider()


def test_background_preload_is_opt_in(monkeypatch, vm):
    from backend.services.vision import provider
    monkeypatch.setattr(config, "VISION_PROVIDER", "local")
    monkeypatch.setattr(config, "VISION_PRELOAD", False)
    assert provider.start_background_preload() is False
    monkeypatch.setattr(config, "VISION_PRELOAD", True)
    monkeypatch.setattr(config, "VISION_PROVIDER", "cloud")
    assert provider.start_background_preload() is False
    monkeypatch.setattr(config, "VISION_PROVIDER", "local")
    monkeypatch.setattr(model, "_instance", None)
    loaded = threading.Event()
    monkeypatch.setattr(model, "load_model", lambda: loaded.set() or vm)
    assert provider.start_background_preload() is True
    assert loaded.wait(10)
    assert model.get_vision_model() is vm


@pytest.mark.parametrize("value", ["cloud", "unknown-provider"])
def test_api_unconfigured_provider_returns_503(post, monkeypatch, value):
    monkeypatch.setattr(config, "VISION_PROVIDER", value)
    status, body, _ = post([("file", "x.dcm", make_dicom(ramp_image()), None)])
    assert status == 503
    assert body["detail"] == "Vision service is not available"


def test_full_app_registers_vision_route():
    if not ANYIO_OK:
        pytest.skip("backend.main cannot be served: the ssl module is blocked in this environment")
    from fastapi.testclient import TestClient
    from backend.main import app
    assert "/api/v1/vision/screen" in {r.path for r in app.routes}
    with TestClient(app) as client:
        resp = client.post("/api/v1/vision/screen",
                           files={"file": ("x.txt", b"not an image", "text/plain")})
    assert resp.status_code == 415
