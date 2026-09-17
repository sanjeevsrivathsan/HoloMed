"""Chest radiograph ingestion and preprocessing (validated in Phase 2).

Pipeline (pixel-intensity preprocessing for radiographs):
  decode (PNG/JPEG via PIL, DICOM via pydicom)
  -> single-channel grayscale in [0, maxval]
  -> xrv.utils.normalize(img, maxval)            # [-1024, 1024]
  -> xrv.datasets.XRayCenterCrop                 # square on the short side
  -> bilinear resize (align_corners=False)       # 224x224
  -> float32 tensor [1, 1, 224, 224], finite
"""
import io
import warnings
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np
import pydicom
import torch
import torch.nn.functional as F
import torchxrayvision as xrv
from PIL import Image, UnidentifiedImageError
from pydicom.pixels import apply_modality_lut, apply_voi_lut

from .constants import INPUT_SIZE
from .errors import InvalidImageError, UnsupportedImageError  # noqa: F401  (re-exported)

# Chest radiograph modalities accepted for DICOM input (empty Modality is allowed).
ALLOWED_DICOM_MODALITIES = {"CR", "DX"}
MAX_PIXELS = 12000 * 12000
MIN_SIDE = 64


@dataclass
class DecodedImage:
    pixels: np.ndarray            # 2D float64 in [0, maxval]
    maxval: float
    format: str                   # png | jpeg | dicom
    source_mode: str
    steps: List[str] = field(default_factory=list)
    bits_stored: Optional[int] = None
    modality: Optional[str] = None
    transfer_syntax: Optional[str] = None


@dataclass
class PreprocessedImage:
    tensor: torch.Tensor          # [1, 1, 224, 224] float32, CPU
    display: np.ndarray           # 2D uint8 rendering of the decoded image
    crop: Tuple[int, int, int]    # (y0, x0, size) in display coordinates
    decoded: DecodedImage
    steps: List[str]


def detect_format(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if len(data) >= 132 and data[128:132] == b"DICM":
        return "dicom"
    raise UnsupportedImageError(
        "Unsupported file type. Upload a PNG, JPEG, or DICOM (Part 10) chest radiograph.",
        media_type=True,
    )


def _check_dims(h: int, w: int) -> None:
    if h < MIN_SIDE or w < MIN_SIDE:
        raise UnsupportedImageError(f"Image is too small ({w}x{h}); minimum side is {MIN_SIDE} px")
    if h * w > MAX_PIXELS:
        raise UnsupportedImageError("Image dimensions exceed the supported maximum")


def decode_raster(data: bytes, fmt: str) -> DecodedImage:
    """PNG/JPEG -> grayscale. 8-bit sources use maxval 255, 16-bit use 65535."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise InvalidImageError(f"Could not decode {fmt.upper()} image") from exc
    if getattr(img, "n_frames", 1) > 1:
        raise UnsupportedImageError("Multi-frame images are not supported")
    _check_dims(img.height, img.width)
    mode = img.mode
    if mode == "L":
        arr, maxval, step = np.asarray(img, dtype=np.float64), 255.0, "grayscale (L) read"
    elif mode in ("I;16", "I;16B", "I;16L"):
        arr, maxval, step = np.asarray(img, dtype=np.float64), 65535.0, f"16-bit grayscale ({mode}) read"
    elif mode == "I":
        arr = np.asarray(img, dtype=np.float64)
        if arr.min() < 0 or arr.max() > 65535:
            raise UnsupportedImageError("32-bit integer images outside the 16-bit range are not supported")
        maxval, step = 65535.0, "32-bit integer grayscale (I) read as 16-bit"
    else:
        arr = np.asarray(img.convert("L"), dtype=np.float64)
        maxval, step = 255.0, f"converted {mode} -> L (PIL luminance)"
    return DecodedImage(pixels=arr, maxval=maxval, format=fmt, source_mode=mode,
                        steps=[f"{fmt.upper()} decoded {img.width}x{img.height}; {step}; maxval={maxval:g}"],
                        bits_stored=16 if maxval > 255 else 8)


def decode_dicom(data: bytes) -> DecodedImage:
    """DICOM radiograph -> grayscale with MONOCHROME2 polarity.

    Applies Modality LUT/rescale and VOI LUT/windowing when present (then
    min-max scales to [0, 255]); inverts MONOCHROME1.
    """
    try:
        ds = pydicom.dcmread(io.BytesIO(data))
    except Exception as exc:
        raise InvalidImageError("Could not parse DICOM file") from exc
    if "PixelData" not in ds:
        raise UnsupportedImageError("DICOM file contains no pixel data")
    modality = str(ds.get("Modality", "") or "").upper()
    if modality and modality not in ALLOWED_DICOM_MODALITIES:
        raise UnsupportedImageError(
            f"Unsupported DICOM modality {modality!r}; expected a chest radiograph (CR or DX)")
    photometric = str(ds.get("PhotometricInterpretation", "") or "")
    if int(ds.get("SamplesPerPixel", 1)) != 1 or photometric not in ("MONOCHROME1", "MONOCHROME2"):
        raise UnsupportedImageError(
            f"Unsupported DICOM photometric interpretation {photometric or 'unknown'!r}; "
            "expected single-channel MONOCHROME1/MONOCHROME2")
    if int(ds.get("NumberOfFrames", 1) or 1) > 1:
        raise UnsupportedImageError("Multi-frame DICOM is not supported")
    try:
        rows, cols, bits = int(ds.Rows), int(ds.Columns), int(ds.BitsStored)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidImageError("DICOM image attributes are missing or invalid") from exc
    _check_dims(rows, cols)
    ts = ds.file_meta.TransferSyntaxUID if "TransferSyntaxUID" in ds.file_meta else None
    ts_name = ts.name if ts is not None else "unknown"
    try:
        arr = ds.pixel_array.astype(np.float64)
    except (NotImplementedError, RuntimeError) as exc:
        raise UnsupportedImageError(
            f"DICOM transfer syntax {ts_name!r} cannot be decoded by the installed decoders") from exc
    except Exception as exc:
        raise InvalidImageError("DICOM pixel data is invalid or truncated") from exc
    if arr.ndim != 2 or arr.shape != (rows, cols):
        raise InvalidImageError("DICOM pixel data does not match the declared dimensions")
    if not np.isfinite(arr).all():
        raise InvalidImageError("DICOM pixel data contains non-finite values")

    steps = [f"DICOM decoded {cols}x{rows} ({ts_name}), range [{arr.min():g}, {arr.max():g}]"]
    maxval = float(2 ** bits - 1)
    lut_applied = False
    if "ModalityLUTSequence" in ds or "RescaleSlope" in ds or "RescaleIntercept" in ds:
        arr = np.asarray(apply_modality_lut(arr, ds), dtype=np.float64)
        steps.append("Modality LUT / rescale applied")
        lut_applied = True
    if "VOILUTSequence" in ds or "WindowCenter" in ds:
        arr = np.asarray(apply_voi_lut(arr, ds), dtype=np.float64)
        steps.append("VOI LUT / windowing applied")
        lut_applied = True
    if lut_applied:
        lo, hi = float(arr.min()), float(arr.max())
        if hi <= lo:
            raise InvalidImageError("DICOM image has no intensity variation after LUT")
        arr = (arr - lo) / (hi - lo) * 255.0
        maxval = 255.0
        steps.append("min-max scaled to [0, 255] after LUT")
    elif arr.min() < 0 or arr.max() > maxval:
        raise InvalidImageError("DICOM pixel values exceed the declared BitsStored range")
    if photometric == "MONOCHROME1":
        arr = maxval - arr
        steps.append("MONOCHROME1 inverted to MONOCHROME2 polarity")
    else:
        steps.append("MONOCHROME2: no inversion")
    steps.append(f"maxval={maxval:g} (BitsStored={bits})")
    return DecodedImage(pixels=arr, maxval=maxval, format="dicom", source_mode=photometric,
                        steps=steps, bits_stored=bits, modality=modality or None,
                        transfer_syntax=ts_name)


def decode_image(data: bytes) -> DecodedImage:
    if not data:
        raise InvalidImageError("Empty upload")
    fmt = detect_format(data)
    return decode_dicom(data) if fmt == "dicom" else decode_raster(data, fmt)


def to_model_tensor(pixels: np.ndarray, maxval: float) -> Tuple[torch.Tensor, Tuple[int, int, int]]:
    """TorchXRayVision normalization -> center crop -> bilinear 224x224 (Phase 2 path)."""
    norm = xrv.utils.normalize(pixels, maxval)
    chw = norm[None, :, :]
    _, h, w = chw.shape
    size = min(h, w)
    crop = (h // 2 - size // 2, w // 2 - size // 2, size)
    cropped = xrv.datasets.XRayCenterCrop()(chw)
    t = torch.from_numpy(np.ascontiguousarray(cropped[None])).float()
    t = F.interpolate(t, size=(INPUT_SIZE, INPUT_SIZE), mode="bilinear", align_corners=False)
    if tuple(t.shape) != (1, 1, INPUT_SIZE, INPUT_SIZE) or not torch.isfinite(t).all():
        raise InvalidImageError("Preprocessing produced an invalid tensor")
    return t, crop


def to_display_uint8(pixels: np.ndarray, maxval: float) -> np.ndarray:
    return np.clip(pixels / maxval * 255.0, 0, 255).round().astype(np.uint8)


def preprocess(data: bytes) -> PreprocessedImage:
    decoded = decode_image(data)
    tensor, crop = to_model_tensor(decoded.pixels, decoded.maxval)
    steps = decoded.steps + [
        f"xrv.utils.normalize(maxval={decoded.maxval:g}) -> [-1024, 1024]",
        f"XRayCenterCrop -> {crop[2]}x{crop[2]}",
        f"bilinear resize -> {INPUT_SIZE}x{INPUT_SIZE}",
        f"tensor [1, 1, {INPUT_SIZE}, {INPUT_SIZE}] float32",
    ]
    return PreprocessedImage(tensor=tensor, display=to_display_uint8(decoded.pixels, decoded.maxval),
                             crop=crop, decoded=decoded, steps=steps)
