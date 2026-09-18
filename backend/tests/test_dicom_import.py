"""Bulk DICOM import (files, folder, ZIP) into the selected patient.

Import mechanics, ZIP safety and isolation use small DICOM instances generated in the test (as the
other patient tests do). CT import and DICOMweb/OHIF readiness use real de-identified studies from
the workspace's OHIF test data (DICOM-TestData); those tests are skipped when it is not present.
The import runs in a background thread, so the tests use a file-backed SQLite database."""
import io
import os
import stat
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from sqlmodel import Session, SQLModel, create_engine, select

from backend import config
from backend.database import get_session
from backend.main import app
from backend.models import AuditLog, Instance
from backend.services import dicom_import, storage

DICOM_JSON = {"Accept": "application/dicom+json"}
TERMINAL = ("done", "failed", "cancelled")


def _testdata_dir():
    env = os.getenv("HOLOMED_DICOM_TESTDATA")
    candidates = [Path(env)] if env else []
    candidates += [p / "DICOM-TestData" / "viewer-testdata-master" / "dcm" for p in Path(__file__).resolve().parents]
    return next((c for c in candidates if c.is_dir()), None)


TESTDATA = _testdata_dir()
# 143-slice chest CT + one SR, de-identified (PatientIdentityRemoved=YES), uncompressed.
CT_DIR = TESTDATA / "scoord3d-and-scoord" / "scoord-bounding-box" if TESTDATA else None
MR_DIR = TESTDATA / "Dummy" if TESTDATA else None            # a second, unrelated study (MR + DOC)
needs_ct = pytest.mark.skipif(not (CT_DIR and CT_DIR.is_dir()), reason="DICOM-TestData CT fixture not present")


def _modality(path: Path) -> str:
    import pydicom
    return str(pydicom.dcmread(str(path), stop_before_pixels=True).Modality)


@pytest.fixture(scope="module")
def ct_files():
    files = sorted(CT_DIR.iterdir())
    return [f for f in files if _modality(f) == "CT"], [f for f in files if _modality(f) != "CT"]


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'import.db'}", connect_args={"check_same_thread": False})
    storage_dir = tmp_path / "storage"
    storage_dir.mkdir()
    monkeypatch.setattr(storage, "STORAGE_DIR", str(storage_dir))
    SQLModel.metadata.create_all(engine)
    dicom_import._jobs.clear()               # user ids restart in every test database

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        client.engine = engine
        client.storage_dir = storage_dir
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def login(client, email):
    client.cookies.clear()
    client.post("/api/v1/auth/register", params={"email": email, "password": "password123"})
    assert client.post("/api/v1/auth/login", data={"username": email, "password": "password123"}).status_code == 200


def patient(client, name="Import Patient", code=None):
    resp = client.post("/api/v1/patients", json={"name": name, **({"patient_code": code} if code else {})})
    assert resp.status_code == 201, resp.text
    return resp.json()


def instance(study=None, series=None, sop=None, number=1, modality="CT", dicom_patient_id="SYN-1", preamble=True):
    """A small, valid DICOM instance generated for the test (not a clinical image)."""
    sop = sop or generate_uid()
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.file_meta.MediaStorageSOPInstanceUID = sop
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID, ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.2", sop
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study or generate_uid(), series or generate_uid()
    ds.PatientName, ds.PatientID = "Synthetic^Import", dicom_patient_id
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = modality, 1, number
    ds.StudyDescription, ds.SeriesDescription = "Synthetic import study", "Synthetic series"
    ds.Rows, ds.Columns = 4, 4
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PixelRepresentation = 1, "MONOCHROME2", 0
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelData = (np.arange(16, dtype=np.uint16) * number).tobytes()
    out = io.BytesIO()
    if preamble:
        ds.save_as(out, enforce_file_format=True)
    else:
        del ds.file_meta
        ds.save_as(out, implicit_vr=True, little_endian=True)   # raw data set, no preamble/"DICM"
    return out.getvalue()


def series_of(n, study=None, series=None, **kw):
    study, series = study or generate_uid(), series or generate_uid()
    return [instance(study, series, number=i + 1, **kw) for i in range(n)], study, series


def zip_bytes(entries, compression=zipfile.ZIP_STORED):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return out.getvalue()


def base(pid):
    return f"/api/v1/patients/{pid}/imaging/imports"


def wait(client, pid, job_id, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"{base(pid)}/{job_id}").json()
        if job["stage"] in TERMINAL:
            return job
        time.sleep(0.05)
    raise AssertionError(f"import did not finish: {job}")


def run_files(client, pid, files, source="files", batch=100):
    job = client.post(base(pid), json={"source": source})
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]
    for i in range(0, len(files), batch):
        resp = client.post(f"{base(pid)}/{job_id}/files",
                           files=[("files", (name, data, "application/octet-stream")) for name, data in files[i:i + batch]])
        assert resp.status_code == 200, resp.text
    assert client.post(f"{base(pid)}/{job_id}/start").status_code == 202
    return wait(client, pid, job_id)


def put_archive(client, pid, data, name="study.zip"):
    job_id = client.post(base(pid), json={"source": "zip"}).json()["id"]
    resp = client.put(f"{base(pid)}/{job_id}/archive", params={"filename": name}, content=data,
                      headers={"Content-Type": "application/zip"})
    return job_id, resp


def run_zip(client, pid, data, name="study.zip"):
    job_id, resp = put_archive(client, pid, data, name)
    assert resp.status_code == 200, resp.text
    assert resp.json()["archive"]["name"] == name and resp.json()["archive"]["size"] == len(data)
    assert client.post(f"{base(pid)}/{job_id}/start").status_code == 202
    return wait(client, pid, job_id)


def imaging(client, pid):
    return client.get(f"/api/v1/patients/{pid}/imaging").json()


def assert_clean(job_id):
    assert not os.path.exists(dicom_import._jobs[job_id].tmp_dir), "temporary import directory was not removed"


# ── A–D: files and folders ────────────────────────────────────────────────────

def test_a_one_dicom_file(client):
    login(client, "imp-a@example.com")
    p = patient(client)
    job = run_files(client, p["id"], [("one.dcm", instance())])
    assert job["stage"] == "done" and job["counts"]["instances_imported"] == 1
    assert (job["counts"]["studies"], job["counts"]["series"]) == (1, 1)
    assert imaging(client, p["id"])[0]["instance_count"] == 1
    assert_clean(job["id"])


def test_b_multiple_files_form_one_study_and_series(client):
    login(client, "imp-b@example.com")
    p = patient(client)
    files, study, series = series_of(12)
    job = run_files(client, p["id"], [(f"slice{i}.dcm", d) for i, d in enumerate(reversed(files))], batch=5)
    c = job["counts"]
    assert (c["files_received"], c["dicom_files"], c["instances_imported"], c["studies"], c["series"]) == (12, 12, 12, 1, 1)
    rows = imaging(client, p["id"])
    assert len(rows) == 1 and rows[0]["study_instance_uid"] == study
    assert rows[0]["series"][0]["series_instance_uid"] == series and rows[0]["instance_count"] == 12


def test_c_folder_upload_detects_dicom_by_content(client):
    login(client, "imp-c@example.com")
    p = patient(client)
    files, _, _ = series_of(3)
    job = run_files(client, p["id"], [
        ("CT/IM0001", files[0]),                         # no extension, DICM preamble
        ("CT/IM0002.dcm", files[1]),
        ("CT/raw0003", instance(preamble=False)),   # raw data set: recognised, not importable
        ("CT/notes.txt", b"not an image"),
        ("CT/.DS_Store", b"\x00\x00\x00\x01Bud1"),
        ("CT/thumb.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64),
    ], source="folder")
    c = job["counts"]
    assert (c["files_received"], c["dicom_files"], c["skipped_non_dicom"], c["invalid_dicom"]) == (6, 2, 3, 1)
    assert c["instances_imported"] == 2
    reasons = {s["name"]: s["reason"] for s in job["skipped"]}
    assert set(reasons) == {"CT/notes.txt", "CT/.DS_Store", "CT/thumb.png", "CT/raw0003"}
    assert "Part 10" in reasons["CT/raw0003"]


def test_d_nested_folder_upload_groups_series(client):
    login(client, "imp-d@example.com")
    p = patient(client)
    study = generate_uid()
    s1, _, uid1 = series_of(4, study=study)
    s2, _, uid2 = series_of(2, study=study)
    files = [(f"Patient/Study/Series1/deep/{i}", d) for i, d in enumerate(s1)]
    files += [(f"Patient/Study/Series2/{i}.dcm", d) for i, d in enumerate(s2)]
    job = run_files(client, p["id"], files, source="folder")
    assert (job["counts"]["studies"], job["counts"]["series"], job["counts"]["instances_imported"]) == (1, 2, 6)
    row = imaging(client, p["id"])[0]
    assert {s["series_instance_uid"]: s["instance_count"] for s in row["series"]} == {uid1: 4, uid2: 2}


# ── E–G: ZIPs of real studies ─────────────────────────────────────────────────

@needs_ct
def test_e_zip_with_one_ct_series(client, ct_files):
    ct, _ = ct_files
    login(client, "imp-e@example.com")
    p = patient(client)
    job = run_zip(client, p["id"], zip_bytes([(f"CT/{f.name}", f.read_bytes()) for f in ct]))
    c = job["counts"]
    assert job["stage"] == "done", job
    assert (c["studies"], c["series"], c["instances_imported"], c["failed"]) == (1, 1, len(ct), 0)
    assert len(ct) == 143
    rows = imaging(client, p["id"])
    assert len(rows) == 1 and rows[0]["modality"] == "CT" and rows[0]["series_count"] == 1
    assert rows[0]["instance_count"] == 143 and rows[0]["series"][0]["rows"] == 512
    # stored bytes are the original files
    with Session(client.engine) as s:
        stored = {i.sop_instance_uid: i.storage_key for i in s.exec(select(Instance)).all()}
    import pydicom
    sample = ct[70]
    sop = str(pydicom.dcmread(str(sample), stop_before_pixels=True).SOPInstanceUID)
    assert (client.storage_dir / stored[sop]).read_bytes() == sample.read_bytes()
    assert_clean(job["id"])


@needs_ct
def test_f_zip_with_multiple_series(client, ct_files):
    ct, other = ct_files
    login(client, "imp-f@example.com")
    p = patient(client)
    job = run_zip(client, p["id"], zip_bytes([(f"s/{f.name}", f.read_bytes()) for f in ct + other], zipfile.ZIP_DEFLATED))
    assert (job["counts"]["studies"], job["counts"]["series"]) == (1, 2)
    counts = sorted(s["instance_count"] for s in job["studies"][0]["series"])
    assert counts == [1, 143]
    assert imaging(client, p["id"])[0]["series_count"] == 2


@needs_ct
@pytest.mark.skipif(not (MR_DIR and MR_DIR.is_dir()), reason="DICOM-TestData MR fixture not present")
def test_g_zip_with_multiple_studies(client, ct_files):
    ct, _ = ct_files
    login(client, "imp-g@example.com")
    p = patient(client)
    entries = [(f"a/ct/{f.name}", f.read_bytes()) for f in ct[:20]]
    entries += [(f"b/mr/{f.name}", f.read_bytes()) for f in sorted(MR_DIR.iterdir())]
    job = run_zip(client, p["id"], zip_bytes(entries))
    assert job["counts"]["studies"] == 2 and job["counts"]["instances_imported"] == len(entries)
    assert len(imaging(client, p["id"])) == 2


# ── H–J: skipped, invalid, duplicate ──────────────────────────────────────────

def test_h_zip_with_non_dicom_files(client):
    login(client, "imp-h@example.com")
    p = patient(client)
    files, _, _ = series_of(3)
    job = run_zip(client, p["id"], zip_bytes([(f"dcm/{i}", d) for i, d in enumerate(files)] + [
        ("README.txt", b"hello"), ("report.pdf", b"%PDF-1.4 ..."), ("__MACOSX/dcm/._0", b"\x00\x05\x16\x07"),
        ("nested.zip", zip_bytes([("x.txt", b"x")]))], zipfile.ZIP_DEFLATED))
    c = job["counts"]
    assert (c["files_received"], c["instances_imported"], c["skipped_non_dicom"], c["invalid_dicom"]) == (7, 3, 4, 0)


def test_i_invalid_dicom_is_reported_not_imported(client):
    login(client, "imp-i@example.com")
    p = patient(client)
    good = instance()
    no_sop = bytearray(instance())
    import pydicom
    ds = pydicom.dcmread(io.BytesIO(bytes(no_sop)))
    del ds.SOPInstanceUID
    missing = io.BytesIO()
    ds.save_as(missing)
    job = run_files(client, p["id"], [
        ("good.dcm", good),
        ("truncated.dcm", b"\x00" * 128 + b"DICM" + b"\x02\x00\x10\x00UI\xff\xff"),   # preamble, broken body
        ("missing-sop.dcm", missing.getvalue()),
        ("text.dcm", b"this is not dicom at all"),
    ])
    c = job["counts"]
    assert (c["dicom_files"], c["invalid_dicom"], c["instances_imported"]) == (1, 3, 1)
    reasons = {s["name"]: s["reason"] for s in job["skipped"]}
    assert "SOPInstanceUID" in reasons["missing-sop.dcm"] and set(reasons) == {"truncated.dcm", "missing-sop.dcm", "text.dcm"}


def test_j_duplicate_sop_instances_follow_existing_dedup(client):
    login(client, "imp-j@example.com")
    p = patient(client)
    files, _, _ = series_of(3)
    job = run_files(client, p["id"], [("a.dcm", files[0]), ("b.dcm", files[1]), ("copy-of-a.dcm", files[0])])
    assert (job["counts"]["instances_imported"], job["counts"]["duplicates"]) == (2, 1)
    again = run_zip(client, p["id"], zip_bytes([(f"{i}.dcm", d) for i, d in enumerate(files)]))
    assert (again["counts"]["instances_imported"], again["counts"]["duplicates"]) == (1, 2)
    assert imaging(client, p["id"])[0]["instance_count"] == 3
    # the single-file upload keeps its behaviour on the same data
    resp = client.post(f"/api/v1/patients/{p['id']}/imaging", files={"file": ("a.dcm", files[0], "application/dicom")})
    assert resp.status_code == 200 and resp.json()["created"] is False
    with Session(client.engine) as s:
        assert len(s.exec(select(Instance)).all()) == 3


# ── K–N: ZIP safety ───────────────────────────────────────────────────────────

def _zip_with_member(info: zipfile.ZipInfo, data=b"x"):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(info, data)
    return out.getvalue()


@pytest.mark.parametrize("name", ["../evil.dcm", "a/../../evil.dcm", "/abs/evil.dcm", "C:/evil.dcm", "..\\evil.dcm"])
def test_k_zip_path_traversal_and_absolute_paths_are_rejected(client, tmp_path, name):
    login(client, "imp-k@example.com")
    p = patient(client)
    info = zipfile.ZipInfo("placeholder")
    info.filename = name                     # ZipInfo normalises on construction; set the raw name
    job_id, resp = put_archive(client, p["id"], _zip_with_member(info, instance()))
    assert resp.status_code == 400 and "Unsafe ZIP archive" in resp.json()["detail"], resp.text
    assert not (Path.cwd() / "evil.dcm").exists() and not (tmp_path.parent / "evil.dcm").exists()
    assert client.post(f"{base(p['id'])}/{job_id}/start").status_code == 409   # nothing to import
    client.delete(f"{base(p['id'])}/{job_id}")
    assert_clean(job_id)


def test_k_zip_symlink_member_is_rejected(client):
    login(client, "imp-k2@example.com")
    p = patient(client)
    info = zipfile.ZipInfo("link.dcm")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    _, resp = put_archive(client, p["id"], _zip_with_member(info, b"/etc/passwd"))
    assert resp.status_code == 400 and "symbolic link" in resp.json()["detail"]


def test_l_oversized_zip_is_rejected(client, monkeypatch):
    login(client, "imp-l@example.com")
    p = patient(client)
    monkeypatch.setattr(config, "IMPORT_MAX_ARCHIVE_BYTES", 4096)
    files, _, _ = series_of(20)
    job_id, resp = put_archive(client, p["id"], zip_bytes([(f"{i}.dcm", d) for i, d in enumerate(files)]))
    assert resp.status_code == 413 and "larger than" in resp.json()["detail"]
    client.delete(f"{base(p['id'])}/{job_id}")
    assert_clean(job_id)


def test_m_excessive_extracted_size_and_compression_bombs_are_rejected(client, monkeypatch):
    login(client, "imp-m@example.com")
    p = patient(client)
    files, _, _ = series_of(10)
    monkeypatch.setattr(config, "IMPORT_MAX_EXTRACTED_BYTES", 5000)
    _, resp = put_archive(client, p["id"], zip_bytes([(f"{i}.dcm", d) for i, d in enumerate(files)]))
    assert resp.status_code == 413 and "expands to more than" in resp.json()["detail"]
    monkeypatch.setattr(config, "IMPORT_MAX_EXTRACTED_BYTES", 1 << 30)
    bomb = zip_bytes([("bomb.dcm", b"\x00" * (16 * 1024 * 1024))], zipfile.ZIP_DEFLATED)   # ~1000:1
    _, resp = put_archive(client, p["id"], bomb)
    assert resp.status_code == 400 and "compression ratio" in resp.json()["detail"]


def test_m_member_larger_than_declared_is_stopped_while_extracting(client, monkeypatch):
    """Declared sizes in the central directory are enforced during extraction too."""
    login(client, "imp-m2@example.com")
    p = patient(client)
    data = zip_bytes([("a.dcm", instance())])
    job_id, resp = put_archive(client, p["id"], data)
    assert resp.status_code == 200
    real_open = zipfile.ZipFile.open

    def lying_open(self, info, *args, **kwargs):     # simulate a member inflating beyond its header
        stream = real_open(self, info, *args, **kwargs)
        stream.read = lambda n=-1, _r=stream.read: (_r(n) or b"") + b"\x00" * 10
        return stream

    monkeypatch.setattr(zipfile.ZipFile, "open", lying_open)
    assert client.post(f"{base(p['id'])}/{job_id}/start").status_code == 202
    job = wait(client, p["id"], job_id)
    assert job["stage"] == "failed" and "declared sizes" in job["error"]
    assert imaging(client, p["id"]) == []
    assert_clean(job_id)


def test_n_excessive_file_count_is_rejected(client, monkeypatch):
    login(client, "imp-n@example.com")
    p = patient(client)
    monkeypatch.setattr(config, "IMPORT_MAX_FILES", 3)
    files, _, _ = series_of(5)
    _, resp = put_archive(client, p["id"], zip_bytes([(f"{i}.dcm", d) for i, d in enumerate(files)]))
    assert resp.status_code == 413 and "more than 3 files" in resp.json()["detail"]
    job_id = client.post(base(p["id"]), json={"source": "files"}).json()["id"]
    resp = client.post(f"{base(p['id'])}/{job_id}/files", files=[("files", (f"{i}.dcm", d)) for i, d in enumerate(files)])
    assert resp.status_code == 413


# ── O: patient isolation ──────────────────────────────────────────────────────

def test_o_imports_are_bound_to_the_owned_selected_patient(client):
    login(client, "imp-owner@example.com")
    mine = patient(client, "Owner Patient", "HML-OWN-1")
    other_mine = patient(client, "Second Patient", "HML-OWN-2")
    job_id = client.post(base(mine["id"]), json={"source": "files"}).json()["id"]
    # a job is only reachable under the patient it was created for
    assert client.get(f"{base(other_mine['id'])}/{job_id}").status_code == 404
    # the active-patient header and the DICOM header never choose the patient
    labelled = instance(dicom_patient_id="HML-OWN-2")
    resp = client.post(f"{base(mine['id'])}/{job_id}/files", headers={"X-HoloMed-Patient": other_mine["id"]},
                       files=[("files", ("x.dcm", labelled))], data={"patient_id": other_mine["id"]})
    assert resp.status_code == 200
    assert client.post(f"{base(mine['id'])}/{job_id}/start", headers={"X-HoloMed-Patient": other_mine["id"]}).status_code == 202
    job = wait(client, mine["id"], job_id)
    assert job["counts"]["instances_imported"] == 1
    assert any("different patient" in w for w in job["warnings"])
    assert len(imaging(client, mine["id"])) == 1 and imaging(client, other_mine["id"]) == []
    with Session(client.engine) as s:
        audit = s.exec(select(AuditLog).where(AuditLog.action == "dicom_import")).one()
        assert "Synthetic" not in (audit.details or "") and "HML-OWN-2" not in (audit.details or "")

    zip_job = client.post(base(mine["id"]), json={"source": "zip"}).json()["id"]
    login(client, "imp-intruder@example.com")
    theirs = patient(client, "Intruder Patient")
    assert client.post(base(mine["id"]), json={"source": "zip"}).status_code == 404
    assert client.get(f"{base(mine['id'])}/{job_id}").status_code == 404
    assert client.get(f"{base(theirs['id'])}/{job_id}").status_code == 404
    assert client.put(f"{base(theirs['id'])}/{zip_job}/archive", content=zip_bytes([("a.dcm", instance())])).status_code == 404
    assert client.post(f"{base(mine['id'])}/{zip_job}/start").status_code == 404
    assert client.delete(f"{base(theirs['id'])}/{zip_job}").status_code == 404


# ── cancellation and cleanup ──────────────────────────────────────────────────

def test_cancel_before_start_and_during_import_cleans_up(client, monkeypatch):
    login(client, "imp-cancel@example.com")
    p = patient(client)
    job_id, resp = put_archive(client, p["id"], zip_bytes([("a.dcm", instance())]))
    assert client.delete(f"{base(p['id'])}/{job_id}").json()["stage"] == "cancelled"
    assert client.post(f"{base(p['id'])}/{job_id}/start").status_code == 409
    assert_clean(job_id)

    files, _, _ = series_of(6)
    job_id = client.post(base(p["id"]), json={"source": "files"}).json()["id"]
    client.post(f"{base(p['id'])}/{job_id}/files", files=[("files", (f"{i}.dcm", d)) for i, d in enumerate(files)])
    real_store = dicom_import.store_patient_dicom

    def store_then_cancel(*args, **kwargs):
        stored = real_store(*args, **kwargs)
        dicom_import._jobs[job_id].cancel.set()
        return stored

    monkeypatch.setattr(dicom_import, "store_patient_dicom", store_then_cancel)
    client.post(f"{base(p['id'])}/{job_id}/start")
    job = wait(client, p["id"], job_id)
    assert job["stage"] == "cancelled" and job["counts"]["instances_imported"] == 1
    assert_clean(job_id)


def test_failed_import_cleans_up(client, monkeypatch):
    login(client, "imp-fail@example.com")
    p = patient(client)
    monkeypatch.setattr(dicom_import, "_group", lambda job: 1 / 0)
    job = run_zip(client, p["id"], zip_bytes([("a.dcm", instance())]))
    assert job["stage"] == "failed" and job["error"] == "Import failed unexpectedly"
    assert_clean(job["id"])


# ── P: the imported CT through DICOMweb, as OHIF loads it ─────────────────────

@needs_ct
def test_p_imported_ct_is_served_to_ohif(client, ct_files):
    ct, _ = ct_files
    login(client, "imp-p@example.com")
    p = patient(client)
    job = run_zip(client, p["id"], zip_bytes([(f"CT/{f.name}", f.read_bytes()) for f in ct], zipfile.ZIP_DEFLATED))
    study = job["studies"][0]["study_instance_uid"]
    series = job["studies"][0]["series"][0]["series_instance_uid"]
    root = f"/api/v1/patients/{p['id']}/dicomweb"
    config_resp = client.get(f"{root}/ohif-config").json()
    assert config_resp["servers"]["dicomWeb"][0]["qidoRoot"] == root
    studies = client.get(f"{root}/studies", params={"StudyInstanceUID": study}, headers=DICOM_JSON).json()
    assert studies[0]["00201208"]["Value"] == [143] and studies[0]["00080061"]["Value"] == ["CT"]
    series_rows = client.get(f"{root}/studies/{study}/series", headers=DICOM_JSON).json()
    assert series_rows[0]["00201209"]["Value"] == [143]
    metadata = client.get(f"{root}/studies/{study}/series/{series}/metadata").json()
    assert len(metadata) == 143 and all(m["00280010"]["Value"] == [512] for m in metadata)
    positions = sorted(m["00200032"]["Value"][2] for m in metadata)
    assert len(set(positions)) == 143                      # a real volume: one slice per z position
    for m in (metadata[0], metadata[-1]):
        sop = m["00080018"]["Value"][0]
        frame = client.get(f"{root}/studies/{study}/series/{series}/instances/{sop}/frames/1")
        assert frame.status_code == 200 and frame.headers["content-type"].startswith("multipart/related")
        assert len(frame.content) > 512 * 512 * 2
    login(client, "imp-p-other@example.com")
    other = patient(client)
    assert client.get(f"{root}/studies", headers=DICOM_JSON).status_code == 404
    assert client.get(f"/api/v1/patients/{other['id']}/dicomweb/studies", headers=DICOM_JSON).json() == []
