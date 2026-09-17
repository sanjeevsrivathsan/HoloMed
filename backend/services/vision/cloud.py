"""Cloud vision provider: calls the private HoloMed vision worker over HTTPS.

The worker (backend/vision_worker, deployed on Modal) runs the same validated
code and weights as the local provider and returns the same
VisionScreenResponse. This module is torch-free.

Request contract: POST {VISION_CLOUD_URL}/v1/screen, multipart
  file   = raw image bytes (fixed name "upload"; the user's filename is not sent)
  target = optional model output name
  Authorization: Bearer {VISION_CLOUD_TOKEN}

No patient metadata is sent beyond what is inside the uploaded image itself,
and there is no fallback to the local provider on any failure.
"""
import logging
import time
from typing import Optional
from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from ... import config
from .constants import EXPECTED_SHA256, EXPECTED_TARGETS, TARGET_LAYER, WEIGHTS_ID
from .errors import (InvalidImageError, UnknownTargetError, UnsupportedImageError,
                     VisionProviderUnavailable)
from .schemas import SAFETY_MESSAGE, VisionScreenResponse

logger = logging.getLogger(__name__)

MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_B64_CHARS = 12 * 1024 * 1024
MAX_DETAIL_CHARS = 300
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _endpoint(path: str) -> str:
    base = (config.VISION_CLOUD_URL or "").strip().rstrip("/")
    token = (config.VISION_CLOUD_TOKEN or "").strip()
    if not base or not token:
        raise VisionProviderUnavailable("Cloud vision provider is not configured")
    parsed = urlparse(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS):
        raise VisionProviderUnavailable("Cloud vision URL must use HTTPS")
    return f"{base}{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.VISION_CLOUD_TOKEN.strip()}"}


def _detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail", "")
    except Exception:
        detail = ""
    return detail[:MAX_DETAIL_CHARS] if isinstance(detail, str) else ""


def validate_worker_response(payload: object) -> VisionScreenResponse:
    """Accept only a response that matches the validated model and schema."""
    try:
        result = VisionScreenResponse.model_validate(payload)
    except ValidationError as exc:
        raise VisionProviderUnavailable("Cloud vision response failed schema validation") from exc
    names = [f.pathology for f in result.findings]
    problems = []
    if sorted(names) != sorted(EXPECTED_TARGETS):
        problems.append("findings do not match the 18 model outputs")
    if result.model.weights != WEIGHTS_ID or result.model.weight_sha256 != EXPECTED_SHA256:
        problems.append("unexpected model weights")
    if result.model.targets != len(EXPECTED_TARGETS) or result.model.target_list != EXPECTED_TARGETS:
        problems.append("unexpected model target list")
    if result.primary_finding != max(result.findings, key=lambda f: f.score):
        problems.append("primary finding is not the highest model score")
    exp = result.explanation
    listed = {f.pathology: f.score for f in result.findings}
    if exp.target_pathology not in EXPECTED_TARGETS or exp.target_layer != TARGET_LAYER:
        problems.append("unexpected explanation target or layer")
    elif exp.target_pathology not in listed or abs(exp.target_score - listed[exp.target_pathology]) > 1e-6:
        problems.append("explanation score does not match findings")
    for img in (exp.original, exp.heatmap, exp.overlay):
        if len(img.data) > MAX_IMAGE_B64_CHARS:
            problems.append("explanation image too large")
    if problems:
        raise VisionProviderUnavailable("Cloud vision response rejected: " + "; ".join(problems))
    # Safety text is enforced by this backend, never taken from the worker.
    result.safety.message = SAFETY_MESSAGE
    result.safety.requires_clinical_review = True
    result.result_id = None
    return result


class CloudVisionProvider:
    name = "cloud"

    def screen(self, data: bytes, target: Optional[str] = None) -> VisionScreenResponse:
        url = _endpoint("/v1/screen")
        form = {"target": target} if target else {}
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=config.VISION_CLOUD_TIMEOUT_SECONDS, follow_redirects=False) as client:
                resp = client.post(url, headers=_headers(), data=form,
                                   files={"file": ("upload", data, "application/octet-stream")})
        except httpx.TimeoutException as exc:
            logger.warning("Cloud vision request timed out after %.0f ms", (time.perf_counter() - started) * 1000)
            raise VisionProviderUnavailable("Cloud vision request timed out") from exc
        except httpx.HTTPError as exc:
            logger.warning("Cloud vision request failed: %s", type(exc).__name__)
            raise VisionProviderUnavailable("Cloud vision service unreachable") from exc
        elapsed = (time.perf_counter() - started) * 1000
        logger.info("Cloud vision response status=%s in %.0f ms", resp.status_code, elapsed)

        if resp.status_code == 400:
            raise InvalidImageError(_detail(resp) or "Image could not be decoded")
        if resp.status_code == 415:
            raise UnsupportedImageError(_detail(resp) or "Unsupported file type", media_type=True)
        if resp.status_code == 422:
            detail = _detail(resp)
            if "target" in detail.lower():
                raise UnknownTargetError(detail)
            raise UnsupportedImageError(detail or "Unsupported image")
        if resp.status_code == 413:
            raise UnsupportedImageError("File too large for the cloud vision service")
        if resp.status_code in (401, 403):
            raise VisionProviderUnavailable("Cloud vision authentication failed (check server configuration)")
        if resp.status_code != 200:
            raise VisionProviderUnavailable(f"Cloud vision service returned HTTP {resp.status_code}")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise VisionProviderUnavailable("Cloud vision response too large")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise VisionProviderUnavailable("Cloud vision response is not JSON") from exc
        result = validate_worker_response(payload)
        if target and result.explanation.target_pathology != target:
            raise VisionProviderUnavailable("Cloud vision response target mismatch")
        return result

    def status(self) -> dict:
        """Readiness of the remote worker (no URL, token or infrastructure details)."""
        try:
            url = _endpoint("/v1/health")
        except VisionProviderUnavailable:
            return {"configured": False, "model_ready": False}
        reachable, body = False, {}
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                resp = client.get(url, headers=_headers())
            if resp.status_code == 200:
                body, reachable = resp.json(), True
        except (httpx.HTTPError, ValueError):
            reachable, body = False, {}
        ready = isinstance(body, dict) and body.get("model_ready") is True
        return {"configured": True, "model_ready": ready, "reachable": reachable}
