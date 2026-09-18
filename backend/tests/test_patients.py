"""Patient workspace: patient identity, isolation, patient-scoped imaging/DICOMweb/reports, persisted
AI analyses and the patient migration. Synthetic DICOM and a fake vision provider only."""
import io
import os
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend import database
from backend.database import get_session, missing_columns
from backend.main import app
from backend.models import AIAnalysis, Instance, Study
from backend.routers import vision as vision_router
from backend.services import storage
from backend.services.synthetic_pdf import text_pdf
from backend.services.vision.schemas import (EncodedImage, VisionExplanation, VisionFinding, VisionInputInfo,
                                             VisionModelInfo, VisionScreenResponse, VisionTiming)

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
DICOM_JSON = {"Accept": "application/dicom+json"}
HEADER = "X-HoloMed-Patient"
PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABc3UBGAAAAABJRU5ErkJggg=="


def get_session_override():
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", str(tmp_path))
    SQLModel.metadata.create_all(engine)
    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    SQLModel.metadata.drop_all(engine)


def login(client, email):
    client.cookies.clear()
    client.post("/api/v1/auth/register", params={"email": email, "password": "password123"})
    assert client.post("/api/v1/auth/login", data={"username": email, "password": "password123"}).status_code == 200


def make_dicom(modality: str, study_uid: str = None, dicom_patient_id: str = "SYN-1") -> tuple:
    study_uid, series_uid, sop_uid = study_uid or generate_uid(), generate_uid(), generate_uid()
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.file_meta.MediaStorageSOPInstanceUID = sop_uid
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID, ds.SOPInstanceUID = "1.2.840.10008.5.1.4.1.1.7", sop_uid
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.PatientName, ds.PatientID = "Synthetic^Test", dicom_patient_id
    ds.StudyDate, ds.StudyDescription = "20260918", f"Synthetic {modality}"
    ds.Modality, ds.SeriesNumber, ds.InstanceNumber = modality, 1, 1
    ds.Rows, ds.Columns = 16, 12
    ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PixelRepresentation = 1, "MONOCHROME2", 0
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelData = (np.arange(16 * 12, dtype=np.uint16) * 50).tobytes()
    out = io.BytesIO()
    ds.save_as(out, enforce_file_format=True)
    return out.getvalue(), study_uid, series_uid, sop_uid


def create(client, name, code=None, expect=201):
    body = {"name": name, **({"patient_code": code} if code else {})}
    resp = client.post("/api/v1/patients", json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()


def upload_to(client, patient_id, data):
    resp = client.post(f"/api/v1/patients/{patient_id}/imaging", files={"file": ("x.dcm", data, "application/dicom")})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Patients ──────────────────────────────────────────────────────────────────

def test_create_list_update_and_validate_patients(client):
    login(client, "pt-owner@example.com")
    a = create(client, "  Demo Patient   Alpha ", "hml-test-001")
    assert a["patient_code"] == "HML-TEST-001" and a["name"] == "Demo Patient Alpha"
    assert len(a["id"]) == 36 and a["created_at"]
    b = create(client, "Demo Patient Beta")                      # code suggested when omitted
    assert b["patient_code"] == "HML-000001"
    assert create(client, "Duplicate", "HML-TEST-001", expect=409)["detail"].startswith("Patient ID HML-TEST-001")
    create(client, "Case-insensitive duplicate", "hml-test-001", expect=409)
    create(client, "", "HML-X", expect=422)
    create(client, "Bad code", "no spaces allowed", expect=422)
    create(client, "x" * 121, "HML-LONG", expect=422)
    assert [p["patient_code"] for p in client.get("/api/v1/patients").json()] == ["HML-TEST-001", "HML-000001"]
    updated = client.patch(f"/api/v1/patients/{b['id']}", json={"name": "Beta Renamed", "sex": "female"}).json()
    assert updated["name"] == "Beta Renamed" and updated["sex"] == "female"
    assert client.patch(f"/api/v1/patients/{b['id']}", json={"patient_code": "HML-TEST-001"}).status_code == 409


def test_age_and_phone_are_validated_and_persisted(client):
    login(client, "pt-fields@example.com")
    alpha = client.post("/api/v1/patients", json={"name": "Test Patient Alpha", "patient_code": "HML-TEST-002",
                                                  "age": 25, "phone": "  +91 98765   43210 "}).json()
    assert (alpha["age"], alpha["phone"], alpha["sex"]) == (25, "+91 98765 43210", None)
    us = client.post("/api/v1/patients", json={"name": "US", "patient_code": "HML-US", "age": 0,
                                               "phone": "+1 (555) 010-4477"})
    assert us.status_code == 201 and us.json()["age"] == 0
    for bad_age in (-1, 131, 25.5, "25", "abc", True):
        resp = client.post("/api/v1/patients", json={"name": "X", "patient_code": "HML-BAD", "age": bad_age})
        assert resp.status_code == 422, bad_age
    for bad_phone in ("abc", "12345", "+91 98765 43210 12345 67", "++91 98765", "98765+43210"):
        resp = client.post("/api/v1/patients", json={"name": "X", "patient_code": "HML-BAD", "phone": bad_phone})
        assert resp.status_code == 422, bad_phone
    updated = client.patch(f"/api/v1/patients/{alpha['id']}", json={"age": 26, "phone": "+44 20 7946 0958"}).json()
    assert (updated["age"], updated["phone"]) == (26, "+44 20 7946 0958")
    listed = {p["patient_code"]: p for p in client.get("/api/v1/patients").json()}
    assert listed["HML-TEST-002"]["age"] == 26 and "HML-BAD" not in listed


def test_patients_are_isolated_between_users(client):
    login(client, "pt-alice@example.com")
    alice = create(client, "Alice's patient", "HML-A")
    data, study_uid, series_uid, sop_uid = make_dicom("CR")
    upload_to(client, alice["id"], data)

    login(client, "pt-mallory@example.com")
    assert client.get("/api/v1/patients").json() == []
    for path in ("", "/imaging", "/reports", "/clinical", "/timeline", "/analyses", "/dicomweb/ohif-config",
                 "/dicomweb/studies", f"/dicomweb/studies/{study_uid}/series"):
        assert client.get(f"/api/v1/patients/{alice['id']}{path}", headers=DICOM_JSON).status_code == 404, path
    assert client.post(f"/api/v1/patients/{alice['id']}/imaging",
                       files={"file": ("x.dcm", data, "application/dicom")}).status_code == 404
    assert client.get("/api/v1/reports", headers={HEADER: alice["id"]}).status_code == 404
    frames = f"/api/v1/dicomweb/studies/{study_uid}/series/{series_uid}/instances/{sop_uid}/frames/1"
    assert client.get(frames).status_code == 404
    # Mallory's own code space is independent: the same code is allowed for her.
    assert create(client, "Mallory's patient", "HML-A")["patient_code"] == "HML-A"


# ── Imaging + DICOMweb per patient ────────────────────────────────────────────

def test_imaging_belongs_to_one_patient_and_ohif_roots_are_patient_scoped(client):
    login(client, "pt-imaging@example.com")
    a = create(client, "Demo Chest X-Ray Patient", "HML-TEST-001")
    b = create(client, "Demo CT Patient", "HML-TEST-002")
    cr, cr_study, cr_series, cr_sop = make_dicom("CR", dicom_patient_id="SYN-A")
    ct, ct_study, _, _ = make_dicom("CT", dicom_patient_id="SYN-B")
    up = upload_to(client, a["id"], cr)
    assert up == {"instance_id": up["instance_id"], "patient_id": a["id"], "study_instance_uid": cr_study,
                  "series_instance_uid": cr_series, "sop_instance_uid": cr_sop, "modality": "CR", "created": True}
    assert upload_to(client, a["id"], cr)["created"] is False    # re-upload reuses the stored instance
    upload_to(client, b["id"], ct)

    a_imaging = client.get(f"/api/v1/patients/{a['id']}/imaging").json()
    assert [s["study_instance_uid"] for s in a_imaging] == [cr_study]
    row = a_imaging[0]
    assert (row["modality"], row["study_date"], row["series_count"], row["instance_count"]) == ("CR", "2026-09-18", 1, 1)
    assert row["series"][0] | {} == {"series_instance_uid": cr_series, "modality": "CR", "description": None,
                                     "instance_count": 1, "first_sop_instance_uid": cr_sop, "rows": 16, "columns": 12}
    assert [s["study_instance_uid"] for s in client.get(f"/api/v1/patients/{b['id']}/imaging").json()] == [ct_study]

    root_a = f"/api/v1/patients/{a['id']}/dicomweb"
    uids = [s["0020000D"]["Value"][0] for s in client.get(f"{root_a}/studies", headers=DICOM_JSON).json()]
    assert uids == [cr_study]                                     # never B's CT
    assert client.get(f"{root_a}/studies/{ct_study}/series", headers=DICOM_JSON).status_code == 404
    meta = client.get(f"{root_a}/studies/{cr_study}/series/{cr_series}/metadata").json()
    assert meta[0]["00080018"]["Value"] == [cr_sop]
    frame = client.get(f"{root_a}/studies/{cr_study}/series/{cr_series}/instances/{cr_sop}/frames/1")
    assert frame.status_code == 200 and "application/octet-stream" in frame.content.decode("latin-1")[:300]

    config = client.get(f"{root_a}/ohif-config").json()["servers"]["dicomWeb"][0]
    assert config["qidoRoot"] == config["wadoRoot"] == config["wadoUriRoot"] == root_a
    assert config["imageRendering"] == "wadors"

    # QIDO PatientID matching on the account-wide root (OHIF's "other studies of this patient").
    both = client.get("/api/v1/dicomweb/studies", headers=DICOM_JSON).json()
    assert len(both) == 2
    only_a = client.get("/api/v1/dicomweb/studies", params={"00100020": "SYN-A"}, headers=DICOM_JSON).json()
    assert [s["0020000D"]["Value"][0] for s in only_a] == [cr_study]
    assert len(client.get("/api/v1/dicomweb/studies", params={"PatientID": "SYN-*"}, headers=DICOM_JSON).json()) == 2


def test_same_dicom_in_two_patients_stays_separate(client):
    login(client, "pt-shared@example.com")
    a, b = create(client, "A", "HML-1"), create(client, "B", "HML-2")
    data, study_uid, _, _ = make_dicom("CR")
    upload_to(client, a["id"], data)
    upload_to(client, b["id"], data)
    with Session(engine) as s:
        assert len(s.exec(select(Study).where(Study.study_instance_uid == study_uid)).all()) == 2
        assert len(s.exec(select(Instance)).all()) == 2
    for p in (a, b):
        assert len(client.get(f"/api/v1/patients/{p['id']}/dicomweb/studies", headers=DICOM_JSON).json()) == 1


def test_active_patient_header_scopes_legacy_upload_and_lists(client):
    login(client, "pt-header@example.com")
    a, b = create(client, "A", "HML-1"), create(client, "B", "HML-2")
    data, study_uid, _, _ = make_dicom("CR")
    resp = client.post("/api/v1/medical-data/dicom/upload", files={"file": ("x.dcm", data, "application/dicom")},
                       headers={HEADER: b["id"]})
    assert resp.json()["patient_id"] == b["id"]
    assert client.get(f"/api/v1/patients/{a['id']}/imaging").json() == []
    assert client.post("/api/v1/medical-data/dicom/upload", files={"file": ("x.dcm", data, "application/dicom")},
                       headers={HEADER: "00000000-0000-0000-0000-000000000000"}).status_code == 404
    import pydicom
    no_uid = pydicom.dcmread(io.BytesIO(make_dicom("CR")[0]))
    del no_uid.StudyInstanceUID
    out = io.BytesIO()
    no_uid.save_as(out)
    bad = client.post(f"/api/v1/patients/{a['id']}/imaging", files={"file": ("x.dcm", out.getvalue(), "application/dicom")})
    assert bad.status_code == 400 and "missing StudyInstanceUID" in bad.json()["detail"]


# ── Reports ───────────────────────────────────────────────────────────────────

LAB = text_pdf(["SYNTHETIC TEST LAB - NOT REAL PATIENT DATA", "Report Date: 02-Sep-2026",
                "Hemoglobin 13.9 g/dL 13.0 - 17.0"])


def test_reports_belong_to_the_active_patient(client):
    login(client, "pt-reports@example.com")
    a, b = create(client, "A", "HML-1"), create(client, "B", "HML-2")
    resp = client.post("/api/v1/reports", files={"file": ("Lab_Report.pdf", LAB, "application/pdf")},
                       data={"type": "Blood Test"}, headers={HEADER: a["id"]})
    assert resp.status_code == 200, resp.text
    report_id = resp.json()["id"]
    assert [r["id"] for r in client.get(f"/api/v1/patients/{a['id']}/reports").json()] == [report_id]
    assert client.get(f"/api/v1/patients/{b['id']}/reports").json() == []
    assert [r["id"] for r in client.get("/api/v1/reports", headers={HEADER: a["id"]}).json()] == [report_id]
    assert client.get("/api/v1/reports", headers={HEADER: b["id"]}).json() == []
    assert client.get("/api/v1/search/source-references", headers={HEADER: b["id"]}).json() == []
    assert len(client.get("/api/v1/search/source-references", headers={HEADER: a["id"]}).json()) == 1
    events = client.get(f"/api/v1/patients/{a['id']}/timeline").json()["events"]
    assert any(e["type"] == "report" and e["ref"] == str(report_id) for e in events)
    assert client.get(f"/api/v1/patients/{b['id']}/timeline").json()["events"] == []
    counts = {p["patient_code"]: p["report_count"] for p in client.get("/api/v1/patients").json()}
    assert counts == {"HML-1": 1, "HML-2": 0}


# ── AI analyses ───────────────────────────────────────────────────────────────

TARGETS = ["Mass", "Nodule", "Effusion"]


def _image(w=4, h=4):
    return EncodedImage(width=w, height=h, data=PNG_1PX)


class FakeProvider:
    name = "fake"

    def screen(self, data, target=None):
        scores = {"Mass": 0.5589, "Nodule": 0.51, "Effusion": 0.3}
        target = target or "Mass"
        return VisionScreenResponse(
            model=VisionModelInfo(name="TorchXRayVision DenseNet-121", architecture="densenet121",
                                  weights="densenet121-res224-all", weight_sha256="f" * 64, targets=3,
                                  target_list=TARGETS, device="cpu", input_size=224),
            input=VisionInputInfo(format="dicom" if data[128:132] == b"DICM" else "png", width=16, height=12,
                                  source_mode="MONOCHROME2", preprocessing=["fake"]),
            primary_finding=VisionFinding(pathology="Mass", score=0.5589),
            findings=[VisionFinding(pathology=k, score=v) for k, v in scores.items()],
            explanation=VisionExplanation(target_pathology=target, target_score=scores[target],
                                          target_layer="features.denseblock4", original=_image(),
                                          heatmap=_image(), overlay=_image()),
            timing=VisionTiming(preprocessing_ms=1, inference_ms=1, gradcam_ms=1, rendering_ms=1, total_ms=4),
            inferred_at=datetime.utcnow())


@pytest.fixture
def fake_vision(monkeypatch):
    monkeypatch.setattr(vision_router, "get_vision_provider", lambda: FakeProvider())


def screen(client, data, patient_id=None, **fields):
    headers = {HEADER: patient_id} if patient_id else {}
    return client.post("/api/v1/vision/screen", files={"file": ("cxr.dcm", data, "application/dicom")},
                       data={k: str(v).lower() if isinstance(v, bool) else v for k, v in fields.items()},
                       headers=headers)


def test_screening_is_saved_to_patient_and_study_and_can_be_reopened(client, fake_vision):
    login(client, "pt-ai@example.com")
    a, b = create(client, "Demo Chest X-Ray Patient", "HML-TEST-001"), create(client, "B", "HML-2")
    data, study_uid, series_uid, sop_uid = make_dicom("CR")

    unsaved = screen(client, data, a["id"]).json()               # default: nothing stored
    assert unsaved["analysis_id"] is None
    assert client.get(f"/api/v1/patients/{a['id']}/analyses").json() == []
    assert client.get(f"/api/v1/patients/{a['id']}/imaging").json() == []

    saved = screen(client, data, a["id"], save=True).json()
    assert saved["analysis_id"] and saved["patient_id"] == a["id"]
    assert (saved["study_instance_uid"], saved["series_instance_uid"], saved["sop_instance_uid"]) == \
        (study_uid, series_uid, sop_uid)                          # the same study OHIF will open
    assert saved["primary_finding"] == {"pathology": "Mass", "score": 0.5589}
    imaging = client.get(f"/api/v1/patients/{a['id']}/imaging").json()
    assert imaging[0]["study_instance_uid"] == study_uid
    assert imaging[0]["latest_analysis"]["id"] == saved["analysis_id"]

    retarget = screen(client, data, a["id"], target="Nodule", analysis_id=saved["analysis_id"]).json()
    assert retarget["analysis_id"] == saved["analysis_id"] and retarget["explanation"]["target_pathology"] == "Nodule"
    listed = client.get(f"/api/v1/patients/{a['id']}/analyses").json()
    assert len(listed) == 1 and listed[0]["selected_target"] == "Nodule"
    assert listed[0]["model_weights"] == "densenet121-res224-all" and listed[0]["weight_sha256"] == "f" * 64

    reopened = client.get(f"/api/v1/patients/{a['id']}/analyses/{saved['analysis_id']}").json()
    assert reopened["response"]["primary_finding"]["score"] == 0.5589
    assert len(reopened["response"]["findings"]) == 3 and reopened["response"]["result_id"]
    assert reopened["response"]["safety"]["requires_clinical_review"] is True

    assert client.get(f"/api/v1/patients/{b['id']}/analyses").json() == []
    assert client.get(f"/api/v1/patients/{b['id']}/analyses/{saved['analysis_id']}").status_code == 404
    assert screen(client, data, b["id"], analysis_id=saved["analysis_id"]).status_code == 404

    stored = client.post(f"/api/v1/patients/{a['id']}/imaging/{study_uid}/screen").json()
    assert stored["study_instance_uid"] == study_uid and stored["analysis_id"] != saved["analysis_id"]
    assert client.post(f"/api/v1/patients/{b['id']}/imaging/{study_uid}/screen").status_code == 404
    retarget_stored = client.post(f"/api/v1/patients/{a['id']}/imaging/{study_uid}/screen",
                                  params={"target": "Effusion", "analysis_id": stored["analysis_id"]}).json()
    assert retarget_stored["analysis_id"] == stored["analysis_id"]
    assert retarget_stored["explanation"]["target_pathology"] == "Effusion"
    assert client.post(f"/api/v1/patients/{b['id']}/imaging/{study_uid}/screen",
                       params={"analysis_id": stored["analysis_id"]}).status_code == 404
    with Session(engine) as s:
        rows = s.exec(select(AIAnalysis)).all()
    assert len(rows) == 2 and all(r.primary_pathology == "Mass" for r in rows)


# ── Migration ─────────────────────────────────────────────────────────────────

def _alembic_config():
    from alembic.config import Config
    here = os.path.dirname(os.path.dirname(__file__))
    cfg = Config()  # no ini file: env.py then leaves the test run's logging configuration alone
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    return cfg


def test_migrations_upgrade_a_clean_database(tmp_path, monkeypatch):
    from alembic import command
    db = sa_create_engine(f"sqlite:///{tmp_path / 'clean.db'}")
    monkeypatch.setattr(database, "engine", db)
    command.upgrade(_alembic_config(), "head")
    assert missing_columns(db) == []
    assert {"patient", "ai_analysis", "study", "report", "auditlog"} <= set(inspect(db).get_table_names())


def test_patient_migration_preserves_and_backfills_existing_data(tmp_path, monkeypatch):
    from alembic import command
    db = sa_create_engine(f"sqlite:///{tmp_path / 'dev.db'}")
    monkeypatch.setattr(database, "engine", db)
    cfg = _alembic_config()
    command.upgrade(cfg, "7b1a2c3d4e50")
    with db.begin() as conn:
        conn.execute(text("INSERT INTO user (id, email, hashed_password, is_active, created_at) VALUES "
                          "(1, 'a@x', '', 1, '2026-01-01'), (2, 'b@x', '', 1, '2026-01-01')"))
        conn.execute(text("INSERT INTO patient (id, owner_id, display_name) VALUES (10, 1, 'Demo Patient'), "
                          "(11, 1, 'Second'), (12, 2, 'Other user')"))
        conn.execute(text("INSERT INTO report (id, owner_id, patient_id, title, type, source, report_date, status, "
                          "original_filename, mime_type, file_size, storage_key, storage_provider, uploaded_at) VALUES "
                          "(1, 1, NULL, 'Old report', 'Other', 'Upload', '2026-01-01', 'ready', 'a.pdf', "
                          "'application/pdf', 1, 'k', 'local', '2026-01-01 00:00:00')"))
    command.upgrade(cfg, "head")
    with db.connect() as conn:
        patients = conn.execute(text("SELECT id, owner_id, display_name, patient_code, uid FROM patient ORDER BY id")).all()
        report_patient = conn.execute(text("SELECT patient_id FROM report WHERE id = 1")).scalar()
    assert [(p[0], p[1], p[2], p[3]) for p in patients] == [(10, 1, "Demo Patient", "HML-000001"),
                                                          (11, 1, "Second", "HML-000002"),
                                                          (12, 2, "Other user", "HML-000001")]
    assert len({p[4] for p in patients}) == 3 and all(len(p[4]) == 36 for p in patients)
    assert report_patient == 10
    assert missing_columns(db) == []
