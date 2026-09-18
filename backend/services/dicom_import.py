"""Bulk DICOM import into one patient: several DICOM files, a folder of files, or one ZIP archive.

One ImportJob per import:
  create → receive → start → [extract ZIP] → validate → group → import → done | failed | cancelled
  * files/folder: files arrive in batches; each is validated on arrival and staged if it is DICOM.
  * zip: the archive is streamed to disk and its central directory is checked (paths, links, sizes,
    file count, compression ratio) before it is accepted; it is extracted only after `start`.
Everything is staged in a temporary directory created for the job and removed when the job ends —
success, failure, cancellation or expiry. Nothing reaches patient storage before the import stage,
which stores each instance through store_patient_dicom: the same storage, study/series/instance
indexing and de-duplication as a single upload, and original bytes are kept unchanged.

The selected HoloMed patient is authoritative. Patient identities in DICOM headers are compared with
it only to warn; they never choose or change the patient and are never logged or returned.
"""
import io
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple

import pydicom
from fastapi import HTTPException
from sqlmodel import Session

from .. import config
from ..models import Patient, User
from .audit import log_action
from .dicom_service import MAX_UPLOAD_SIZE, store_patient_dicom

logger = logging.getLogger(__name__)

SOURCES = ("files", "folder", "zip")
TERMINAL = ("done", "failed", "cancelled")
TEMP_PREFIX = "holomed-import-"
CHUNK = 1024 * 1024
MAX_ACTIVE_JOBS_PER_USER = 3
MAX_LISTED_SKIPS = 100
DICOMDIR_CLASS = "1.2.840.10008.1.3.10"
_UID_KEYS = ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")
_REQUIRED = _UID_KEYS + ("SOPClassUID",)
_UID = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_PIXEL_DATA_TAG = b"\xe0\x7f\x10\x00"  # (7FE0,0010) little endian
_SYSTEM_FILES = {".ds_store", "thumbs.db", "desktop.ini"}
_DICOM_SUFFIXES = (".dcm", ".dicom", ".dic")
_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
COUNT_KEYS = ("files_received", "bytes_received", "files_validated", "dicom_files", "skipped_non_dicom",
              "invalid_dicom", "failed", "to_import", "instances_imported", "duplicates", "studies", "series")


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int
    max_extracted_bytes: int
    max_files: int
    max_ratio: float
    max_file_bytes: int


def limits() -> Limits:
    return Limits(config.IMPORT_MAX_ARCHIVE_BYTES, config.IMPORT_MAX_EXTRACTED_BYTES, config.IMPORT_MAX_FILES,
                  config.IMPORT_MAX_COMPRESSION_RATIO, MAX_UPLOAD_SIZE)


def _mib(n: int) -> str:
    return f"{n / 1024 ** 2:,.0f} MiB"


class ImportCancelled(Exception):
    pass


class ArchiveRejected(Exception):
    pass


# ── DICOM detection and validation ─────────────────────────────────────────────

def clean_label(name: Optional[str]) -> str:
    """A file's relative path, for diagnostics only (never used as a filesystem path)."""
    text = "".join(c for c in (name or "") if c.isprintable()).replace("\\", "/").strip()
    return text[-255:] or "unnamed"


def _int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify(data: bytes, label: str) -> Tuple[str, object]:
    """Decide from the content what a file is: ('dicom', metadata), ('skipped', reason) for files that
    are not DICOM, or ('invalid', reason) for DICOM that cannot be imported."""
    lowered = label.lower()
    base = lowered.rsplit("/", 1)[-1]
    if base in _SYSTEM_FILES or base.startswith("._") or "__macosx/" in lowered:
        return "skipped", "system file"
    named_dicom = base.endswith(_DICOM_SUFFIXES)
    has_preamble = len(data) >= 132 and data[128:132] == b"DICM"
    # Without the DICM preamble only a raw data set starting with group 0002/0008 is tried.
    if not has_preamble and data[:2] not in (b"\x02\x00", b"\x08\x00"):
        return ("invalid", "not a readable DICOM file") if named_dicom else ("skipped", "not DICOM")
    try:
        ds = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True, force=not has_preamble)
        meta = {key: str(ds.get(key, "") or "").strip() for key in _REQUIRED}
    except Exception:
        return ("invalid", "unreadable DICOM") if has_preamble or named_dicom else ("skipped", "not DICOM")
    file_meta = getattr(ds, "file_meta", None)
    if base == "dicomdir" or str(getattr(file_meta, "MediaStorageSOPClassUID", "") or "") == DICOMDIR_CLASS:
        return "skipped", "DICOMDIR index"
    if not has_preamble:
        if not named_dicom and not (meta["SOPInstanceUID"] and meta["StudyInstanceUID"]):
            return "skipped", "not DICOM"
        # A raw data set without the Part 10 header: storage and DICOMweb read Part 10 files only.
        return "invalid", "not a DICOM Part 10 file (no DICM header)"
    missing = [key for key in _REQUIRED if not meta[key]]
    if missing:
        return "invalid", f"missing {', '.join(missing)}"
    malformed = [key for key in _REQUIRED if len(meta[key]) > 64 or not _UID.match(meta[key])]
    if malformed:
        return "invalid", f"malformed {', '.join(malformed)}"
    rows, columns = _int(ds.get("Rows")), _int(ds.get("Columns"))
    if _PIXEL_DATA_TAG in data and not (rows and columns and rows > 0 and columns > 0):
        return "invalid", "image without valid Rows/Columns"
    meta.update({
        "Modality": str(ds.get("Modality", "") or "").strip(),
        "Rows": rows, "Columns": columns,
        "InstanceNumber": _int(ds.get("InstanceNumber")),
        "SeriesNumber": _int(ds.get("SeriesNumber")),
        "StudyDescription": str(ds.get("StudyDescription", "") or "").strip(),
        "SeriesDescription": str(ds.get("SeriesDescription", "") or "").strip(),
        # Compared with the selected patient only (warnings); never stored, returned or logged.
        "PatientID": str(ds.get("PatientID", "") or "").strip(),
        "PatientName": str(ds.get("PatientName", "") or "").strip(),
    })
    return "dicom", meta


def _name_tokens(name: str) -> frozenset:
    return frozenset(t for t in re.split(r"[\^\s,]+", name.lower()) if t)


def identity_differs(meta: dict, patient: Patient) -> bool:
    """True when the DICOM header names a patient other than the selected HoloMed patient."""
    pid, pname = meta.get("PatientID", ""), meta.get("PatientName", "")
    if not pid and not pname:
        return False
    if pid and pid.upper() == (patient.patient_code or "").upper():
        return False
    if pname and _name_tokens(pname) == _name_tokens(patient.display_name or ""):
        return False
    return True


# ── ZIP safety ─────────────────────────────────────────────────────────────────

def _unsafe_member(info: zipfile.ZipInfo) -> Optional[str]:
    name = info.filename.replace("\\", "/")
    if not name or "\x00" in name:
        return "a member has an empty or invalid name"
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return f"absolute path {name!r}"
    if ".." in name.split("/"):
        return f"path traversal in {name!r}"
    if stat.S_ISLNK(info.external_attr >> 16):
        return f"symbolic link {name!r}"
    if info.flag_bits & 0x1:
        return "encrypted members are not supported"
    if info.compress_type not in _COMPRESSION:
        return f"unsupported compression method in {name!r}"
    return None


def inspect_archive(path: str, archive_size: int, lim: Limits) -> List[zipfile.ZipInfo]:
    """Check a ZIP's central directory before anything is extracted; returns its file members.

    Rejects (400) traversal/absolute paths, links, encryption and suspicious compression ratios;
    rejects (413) archives with too many files or too much uncompressed content."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Not a valid ZIP archive")
    with archive:
        members, total = [], 0
        for info in archive.infolist():
            reason = _unsafe_member(info)
            if reason:
                raise HTTPException(status_code=400, detail=f"Unsafe ZIP archive rejected: {reason}")
            if info.is_dir():
                continue
            members.append(info)
            if len(members) > lim.max_files:
                raise HTTPException(status_code=413, detail=f"ZIP archive contains more than {lim.max_files:,} files")
            total += info.file_size
            if total > lim.max_extracted_bytes:
                raise HTTPException(status_code=413,
                                    detail=f"ZIP archive expands to more than {_mib(lim.max_extracted_bytes)}")
            if info.file_size > CHUNK and info.file_size > lim.max_ratio * max(info.compress_size, 1):
                raise HTTPException(status_code=400, detail="Unsafe ZIP archive rejected: suspicious compression "
                                                            "ratio (possible ZIP bomb)")
        if total > CHUNK and total > lim.max_ratio * max(archive_size, 1):
            raise HTTPException(status_code=400, detail="Unsafe ZIP archive rejected: suspicious compression ratio "
                                                        "(possible ZIP bomb)")
        return members


def _inside(root: str, path: str) -> bool:
    root, path = os.path.realpath(root), os.path.realpath(path)
    return os.path.commonpath([root, path]) == root


# ── Jobs ───────────────────────────────────────────────────────────────────────

@dataclass
class Staged:
    label: str
    path: str
    meta: dict


@dataclass
class ImportJob:
    id: str
    owner_id: int
    patient_id: int
    source: str
    tmp_dir: str
    stage: str = "receiving"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    counts: Dict[str, int] = field(default_factory=lambda: dict.fromkeys(COUNT_KEYS, 0))
    staged: List[Staged] = field(default_factory=list)
    skipped: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    studies: List[dict] = field(default_factory=list)
    archive: Optional[dict] = None
    error: Optional[str] = None
    staged_bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancel: threading.Event = field(default_factory=threading.Event)

    def touch(self, stage: Optional[str] = None) -> None:
        if stage:
            self.stage = stage
        self.updated_at = time.time()

    def note(self, label: str, reason: str) -> None:
        if len(self.skipped) < MAX_LISTED_SKIPS:
            self.skipped.append({"name": label, "reason": reason})

    def view(self) -> dict:
        return {"id": self.id, "source": self.source, "stage": self.stage, "archive": self.archive,
                "counts": dict(self.counts), "studies": self.studies, "skipped": list(self.skipped),
                "warnings": list(self.warnings), "error": self.error,
                "limits": {"max_files": limits().max_files, "max_batch_files": config.IMPORT_MAX_BATCH_FILES,
                           "max_file_bytes": MAX_UPLOAD_SIZE, "max_archive_bytes": limits().max_archive_bytes}}


_jobs: Dict[str, ImportJob] = {}
_jobs_lock = threading.Lock()


def _cleanup(job: ImportJob) -> None:
    job.staged = []
    shutil.rmtree(job.tmp_dir, ignore_errors=True)
    if os.path.exists(job.tmp_dir):
        logger.warning("Could not remove import temp directory %s", job.tmp_dir)


def sweep() -> None:
    """Discard expired jobs and temp directories left behind by a previous process."""
    ttl, now = config.IMPORT_JOB_TTL_SECONDS, time.time()
    with _jobs_lock:
        for job_id, job in list(_jobs.items()):
            if now - job.updated_at < ttl:
                continue
            if job.stage == "receiving":
                job.cancel.set()
                job.touch("cancelled")
                job.error = "Import expired before it was started"
                _cleanup(job)
            if job.stage in TERMINAL:
                del _jobs[job_id]
        known = {os.path.realpath(j.tmp_dir) for j in _jobs.values()}
    base = tempfile.gettempdir()
    try:
        entries = [e for e in os.scandir(base) if e.name.startswith(TEMP_PREFIX) and e.is_dir()]
    except OSError:
        return
    for entry in entries:
        try:
            if os.path.realpath(entry.path) not in known and now - entry.stat().st_mtime > ttl:
                shutil.rmtree(entry.path, ignore_errors=True)
        except OSError:
            pass


def create_job(user: User, patient: Patient, source: str) -> ImportJob:
    if source not in SOURCES:
        raise HTTPException(status_code=422, detail=f"source must be one of: {', '.join(SOURCES)}")
    sweep()
    with _jobs_lock:
        active = [j for j in _jobs.values() if j.owner_id == user.id and j.stage not in TERMINAL]
        if len(active) >= MAX_ACTIVE_JOBS_PER_USER:
            raise HTTPException(status_code=429, detail="Too many imports in progress; wait for one to finish")
        job = ImportJob(id=uuid.uuid4().hex, owner_id=user.id, patient_id=patient.id, source=source,
                        tmp_dir=tempfile.mkdtemp(prefix=TEMP_PREFIX))
        _jobs[job.id] = job
    return job


def get_job(job_id: str, user: User, patient: Patient) -> ImportJob:
    """The job if it belongs to this user and patient; 404 otherwise (no existence oracle)."""
    job = _jobs.get(job_id)
    if job is None or job.owner_id != user.id or job.patient_id != patient.id:
        raise HTTPException(status_code=404, detail="Import not found")
    return job


def _accept(job: ImportJob, label: str, data: bytes, path: Optional[str] = None) -> None:
    """Validate one file; DICOM is staged (written to the job directory unless already there)."""
    job.counts["files_validated"] += 1
    kind, detail = classify(data, label)
    if kind == "skipped":
        job.counts["skipped_non_dicom"] += 1
        job.note(label, str(detail))
    elif kind == "invalid":
        job.counts["invalid_dicom"] += 1
        job.note(label, f"invalid DICOM: {detail}")
    else:
        if path is None:
            path = os.path.join(job.tmp_dir, f"{len(job.staged):06d}.dcm")
            with open(path, "wb") as out:
                out.write(data)
        job.staged.append(Staged(label=label, path=path, meta=detail))
        job.counts["dicom_files"] += 1
    if kind != "dicom" and path and os.path.exists(path):
        os.remove(path)
    job.touch()


def _reject(job: ImportJob, exc: HTTPException) -> None:
    """An upload that breaks a limit or safety rule ends the job; nothing is imported."""
    job.cancel.set()
    job.error = str(exc.detail)
    _cleanup(job)
    job.touch("failed")


def add_files(job: ImportJob, files: List[Tuple[str, BinaryIO]]) -> None:
    """Receive one batch of files (files/folder imports); each is validated as it arrives."""
    lim = limits()
    with job.lock:
        if job.source == "zip":
            raise HTTPException(status_code=409, detail="This import expects a ZIP archive")
        if job.stage != "receiving":
            raise HTTPException(status_code=409, detail=f"Import is already {job.stage}")
        try:
            if len(files) > config.IMPORT_MAX_BATCH_FILES:
                raise HTTPException(status_code=413, detail=f"Send at most {config.IMPORT_MAX_BATCH_FILES} files per request")
            if job.counts["files_received"] + len(files) > lim.max_files:
                raise HTTPException(status_code=413, detail=f"An import can contain at most {lim.max_files:,} files")
            for label, stream in files:
                data = stream.read(lim.max_file_bytes + 1)
                job.counts["files_received"] += 1
                job.counts["bytes_received"] += len(data)
                if len(data) > lim.max_file_bytes:
                    job.counts["files_validated"] += 1
                    job.counts["failed"] += 1
                    job.note(label, f"larger than the {_mib(lim.max_file_bytes)} per-file limit")
                    continue
                job.staged_bytes += len(data)
                if job.staged_bytes > lim.max_extracted_bytes:
                    raise HTTPException(status_code=413,
                                        detail=f"An import can contain at most {_mib(lim.max_extracted_bytes)}")
                _accept(job, label, data)
        except HTTPException as exc:
            _reject(job, exc)
            raise


async def add_archive(job: ImportJob, filename: str, chunks, declared_length: Optional[int]) -> None:
    """Receive the ZIP (zip imports): streamed to the job directory, then its directory is inspected."""
    from starlette.concurrency import run_in_threadpool
    lim = limits()
    if job.source != "zip":
        raise HTTPException(status_code=409, detail="This import expects DICOM files")
    if not job.lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="The archive is already being received")
    try:
        if job.stage != "receiving" or job.archive is not None:
            raise HTTPException(status_code=409, detail="This import already has its archive")
        if declared_length is not None and declared_length > lim.max_archive_bytes:
            raise HTTPException(status_code=413, detail=f"ZIP archive is larger than {_mib(lim.max_archive_bytes)}")
        path = os.path.join(job.tmp_dir, "archive.zip")
        size = 0
        with open(path, "wb") as out:
            async for chunk in chunks:
                size += len(chunk)
                if size > lim.max_archive_bytes:
                    raise HTTPException(status_code=413, detail=f"ZIP archive is larger than {_mib(lim.max_archive_bytes)}")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty upload")
        members = await run_in_threadpool(inspect_archive, path, size, lim)
        job.archive = {"name": clean_label(os.path.basename(filename or "archive.zip")), "size": size,
                       "members": len(members)}
        job.counts["files_received"] = len(members)
        job.counts["bytes_received"] = size
        job.touch()
    except HTTPException as exc:
        if exc.status_code in (400, 413):
            _reject(job, exc)
        raise
    finally:
        job.lock.release()


def start_job(job: ImportJob, bind, user: User, patient: Patient) -> None:
    with job.lock:
        if job.stage != "receiving":
            raise HTTPException(status_code=409, detail=f"Import is already {job.stage}")
        if job.source == "zip" and job.archive is None:
            raise HTTPException(status_code=409, detail="Upload the ZIP archive first")
        if job.source != "zip" and job.counts["files_received"] == 0:
            raise HTTPException(status_code=409, detail="No files were uploaded")
        job.touch("extracting" if job.source == "zip" else "grouping")
    threading.Thread(target=_run, args=(job, bind, user.id, patient.id), daemon=True,
                     name=f"dicom-import-{job.id[:8]}").start()


def cancel_job(job: ImportJob) -> None:
    job.cancel.set()
    with job.lock:
        if job.stage == "receiving":
            job.touch("cancelled")
            _cleanup(job)


def _check_cancel(job: ImportJob) -> None:
    if job.cancel.is_set():
        raise ImportCancelled()


def _extract(job: ImportJob, lim: Limits) -> Iterator[Tuple[str, str]]:
    """Extract file members one by one under generated names (archive paths never reach the
    filesystem), enforcing the declared sizes and the extracted-size budget while writing."""
    path = os.path.join(job.tmp_dir, "archive.zip")
    out_dir = os.path.join(job.tmp_dir, "extracted")
    os.makedirs(out_dir)
    written = 0
    with zipfile.ZipFile(path) as archive:
        members = inspect_archive(path, os.path.getsize(path), lim)
        for index, info in enumerate(members):
            _check_cancel(job)
            label = clean_label(info.filename)
            if info.file_size > lim.max_file_bytes:
                job.counts["files_validated"] += 1
                job.counts["failed"] += 1
                job.note(label, f"larger than the {_mib(lim.max_file_bytes)} per-file limit")
                continue
            dest = os.path.join(out_dir, f"{index:06d}.bin")
            if not _inside(out_dir, dest):
                raise ArchiveRejected("extraction path escaped the temporary directory")
            size = 0
            try:
                with archive.open(info) as src, open(dest, "wb") as out:
                    while True:
                        chunk = src.read(CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        written += len(chunk)
                        if size > info.file_size or written > lim.max_extracted_bytes:
                            raise ArchiveRejected("archive content is larger than its declared sizes")
                        out.write(chunk)
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError):
                job.counts["files_validated"] += 1
                job.counts["failed"] += 1
                job.note(label, "corrupt archive member")
                if os.path.exists(dest):
                    os.remove(dest)
                continue
            yield label, dest
    os.remove(path)


def _group(job: ImportJob) -> List[Staged]:
    """study → series → instance; returns the instances in import order (series by SeriesNumber,
    instances by InstanceNumber). An instance repeated within the upload is counted as a duplicate."""
    studies: Dict[str, dict] = {}
    for item in job.staged:
        m = item.meta
        study = studies.setdefault(m["StudyInstanceUID"], {
            "study_instance_uid": m["StudyInstanceUID"], "description": m["StudyDescription"] or None,
            "modalities": [], "series": {}})
        if m["Modality"] and m["Modality"] not in study["modalities"]:
            study["modalities"].append(m["Modality"])
        series = study["series"].setdefault(m["SeriesInstanceUID"], {
            "series_instance_uid": m["SeriesInstanceUID"], "modality": m["Modality"] or None,
            "description": m["SeriesDescription"] or None, "series_number": m["SeriesNumber"], "items": {}})
        if m["SOPInstanceUID"] in series["items"]:
            job.counts["duplicates"] += 1
            continue
        series["items"][m["SOPInstanceUID"]] = item
    ordered, out = [], []
    for study in studies.values():
        series_list = sorted(study["series"].values(),
                             key=lambda s: s["series_number"] if s["series_number"] is not None else 1 << 30)
        view_series = []
        for s in series_list:
            items = sorted(s["items"].values(), key=lambda i: (
                i.meta["InstanceNumber"] if i.meta["InstanceNumber"] is not None else 1 << 30, i.label))
            ordered += items
            view_series.append({"series_instance_uid": s["series_instance_uid"], "modality": s["modality"],
                                "description": s["description"], "series_number": s["series_number"],
                                "instance_count": len(items), "imported": 0, "duplicates": 0})
        out.append({"study_instance_uid": study["study_instance_uid"], "modality": "/".join(study["modalities"]) or None,
                    "description": study["description"], "series_count": len(view_series),
                    "instance_count": sum(s["instance_count"] for s in view_series), "series": view_series})
    job.studies = out
    job.counts["studies"] = len(out)
    job.counts["series"] = sum(len(s["series"]) for s in out)
    job.counts["to_import"] = len(ordered)
    return ordered


def _run(job: ImportJob, bind, user_id: int, patient_id: int) -> None:
    lim = limits()
    final = "failed"
    try:
        with Session(bind) as session:
            user, patient = session.get(User, user_id), session.get(Patient, patient_id)
            if user is None or patient is None:
                raise ArchiveRejected("patient no longer exists")
            if job.source == "zip":
                extracted = list(_extract(job, lim))
                job.touch("validating")
                for label, path in extracted:
                    _check_cancel(job)
                    with open(path, "rb") as f:
                        data = f.read()
                    _accept(job, label, data, path)
            _check_cancel(job)
            job.touch("grouping")
            ordered = _group(job)
            series_view = {(st["study_instance_uid"], se["series_instance_uid"]): se
                           for st in job.studies for se in st["series"]}
            job.touch("importing")
            mismatched, identities = 0, set()
            for item in ordered:
                _check_cancel(job)
                m = item.meta
                identities.add((m["PatientID"], m["PatientName"]))
                mismatched += identity_differs(m, patient)
                view = series_view[(m["StudyInstanceUID"], m["SeriesInstanceUID"])]
                try:
                    with open(item.path, "rb") as f:
                        stored = store_patient_dicom(session, user, patient, f.read(),
                                                     os.path.basename(item.label))
                except HTTPException as exc:
                    session.rollback()
                    job.counts["failed"] += 1
                    job.note(item.label, str(exc.detail))
                    continue
                except Exception:
                    session.rollback()
                    logger.exception("Storing an imported DICOM instance failed")
                    job.counts["failed"] += 1
                    job.note(item.label, "could not be stored")
                    continue
                key = "instances_imported" if stored.created else "duplicates"
                job.counts[key] += 1
                view["imported" if stored.created else "duplicates"] += 1
                job.touch()
            if len(identities - {("", "")}) > 1:
                job.warnings.append(f"The upload contains images of {len(identities - {('', '')})} different "
                                    "DICOM patients; all were stored under the selected HoloMed patient.")
            if mismatched:
                job.warnings.append(f"{mismatched} instance(s) name a different patient in their DICOM header. "
                                    f"They were stored under {patient.patient_code}; the HoloMed patient and "
                                    "the DICOM files were not changed.")
            log_action(session, user.id, "dicom_import", {
                "source": job.source, "studies": job.counts["studies"], "series": job.counts["series"],
                "imported": job.counts["instances_imported"], "duplicates": job.counts["duplicates"],
                "skipped": job.counts["skipped_non_dicom"], "invalid": job.counts["invalid_dicom"],
                "failed": job.counts["failed"]}, patient_id=patient.id)
            session.commit()
            final = "done"
    except ImportCancelled:
        job.error, final = "Import cancelled", "cancelled"
    except ArchiveRejected as exc:
        job.error, final = f"Unsafe ZIP archive rejected: {exc}", "failed"
    except Exception:
        logger.exception("DICOM import failed")
        job.error, final = "Import failed unexpectedly", "failed"
    finally:
        _cleanup(job)   # before the job reports a terminal stage
    job.touch(final)
