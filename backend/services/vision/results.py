"""Short-lived, in-memory store of structured screening results (torch-free).

Stored per result: owner user id, the 18 model scores, weights identity and a
timestamp. Never image bytes, rendered images, filenames or DICOM metadata.
Entries expire after VISION_RESULT_TTL_SECONDS (default 30 min) and the store
is bounded; nothing is written to disk. Explanations generated for a result
are cached alongside it and expire with it.

The explanation layer reads model scores from here, so a client cannot supply
its own "facts" to the language model.
"""
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional

from ... import config

MAX_RESULTS = 500


@dataclass
class StoredResult:
    owner_id: int
    scores: Dict[str, float]          # pathology -> model score
    primary_pathology: str
    weights: str
    weight_sha256: str
    created: float = field(default_factory=time.monotonic)
    explanations: Dict[str, object] = field(default_factory=dict)  # target -> explanation payload


_lock = threading.Lock()
_results: "OrderedDict[str, StoredResult]" = OrderedDict()


def _expired(rec: StoredResult, now: float) -> bool:
    return now - rec.created > config.VISION_RESULT_TTL_SECONDS


def _purge(now: float) -> None:
    for key in [k for k, v in _results.items() if _expired(v, now)]:
        del _results[key]
    while len(_results) > MAX_RESULTS:
        _results.popitem(last=False)


def register(owner_id: int, scores: Dict[str, float], primary_pathology: str,
             weights: str, weight_sha256: str) -> str:
    result_id = secrets.token_urlsafe(18)
    with _lock:
        now = time.monotonic()
        _purge(now)
        _results[result_id] = StoredResult(owner_id=owner_id, scores=dict(scores),
                                           primary_pathology=primary_pathology,
                                           weights=weights, weight_sha256=weight_sha256)
        _purge(now)
    return result_id


def get(result_id: str, owner_id: int) -> Optional[StoredResult]:
    """The result if it exists, has not expired and belongs to ``owner_id``."""
    with _lock:
        rec = _results.get(result_id)
        if rec is None or rec.owner_id != owner_id or _expired(rec, time.monotonic()):
            return None
        return rec


def get_explanation(result_id: str, owner_id: int, target: str):
    rec = get(result_id, owner_id)
    if rec is None:
        return None
    with _lock:
        return rec.explanations.get(target)


def put_explanation(result_id: str, owner_id: int, target: str, payload) -> None:
    rec = get(result_id, owner_id)
    if rec is not None:
        with _lock:
            rec.explanations[target] = payload


def clear() -> None:
    """Drop everything (tests only)."""
    with _lock:
        _results.clear()
