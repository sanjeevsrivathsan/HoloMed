"""Phase 7A-B regressions: upload request format, explicit processing stages, stage-specific
failures, OCR-robust parsing, optional text AI, schema drift detection."""
import io
import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as sa_create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.database import get_session, missing_columns
from backend.main import app
from backend.models import ExtractedMeasurement, MedicalMeasurement, Report, ReportExtraction
from backend.services import document_extraction, lab_parser, report_pipeline, storage
from backend.services.explanation import report_summary
from backend.services.synthetic_pdf import text_pdf
from backend.services.text_ai.providers import TextAIUnavailable

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

LAB = text_pdf([
    "SYNTHETIC TEST LAB - NOT REAL PATIENT DATA",
    "Sample Collected On: 02-Sep-2026 08:15",
    "HbA1c (Glycosylated Hemoglobin) 6.2 H % 4.0 - 5.6",
    "Hemoglobin 13.4 g/dL 13.0 - 17.0",
    "LDL Cholesterol 138 H mg/dL < 100",
])
SECRET = "Qwerty-Private-Line"


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


def upload(client, content=LAB, name="Lab_Report.pdf", mime="application/pdf", type_="Blood Test"):
    return client.post("/api/v1/reports", files={"file": (name, content, mime)}, data={"type": type_})


def stage_states(client, rid):
    body = client.get(f"/api/v1/reports/{rid}/extraction").json()
    return body, {s["key"]: s["state"] for s in body["stages"]}, {s["key"]: s["detail"] for s in body["stages"]}


def test_pre_7a_json_upload_is_rejected_and_multipart_works(client):
    """Root cause of the reported failure: the old frontend posted JSON.stringify(FormData) == "{}"."""
    login(client, "rootcause@example.com")
    resp = client.post("/api/v1/reports", content=b"{}", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "file"]
    assert client.get("/api/v1/reports").json() == []            # nothing stored
    assert upload(client).status_code == 200                      # the current multipart request works
    assert client.get("/api/v1/reports").json()[0]["status"] == "needs_review"


def test_text_pdf_stages_complete_and_ocr_is_skipped(client, monkeypatch):
    login(client, "stages@example.com")

    def no_ocr(*args, **kwargs):
        raise AssertionError("OCR must not run for a PDF with a text layer")

    monkeypatch.setattr(document_extraction, "_ocr_image", no_ocr)
    rid = upload(client).json()["id"]
    body, states, details = stage_states(client, rid)
    assert body["status"] == "succeeded" and body["stage"] == "done" and body["method"] == "pdf_text"
    assert states == {"upload": "completed", "text_extraction": "completed", "ocr": "skipped",
                      "structured_extraction": "completed", "save": "completed"}
    assert details["ocr"].startswith("Not required")
    assert details["structured_extraction"] == "3 value(s) found"
    assert [s["label"] for s in body["stages"]] == [
        "Upload", "Extract text", "OCR fallback", "Extract structured data", "Save report"]


def test_persisted_report_extraction_and_ownership(client):
    login(client, "persist@example.com")
    rid = upload(client).json()["id"]
    with Session(engine) as s:
        report = s.get(Report, rid)
        extraction = s.exec(select(ReportExtraction).where(ReportExtraction.report_id == rid)).one()
        cands = s.exec(select(ExtractedMeasurement).where(ExtractedMeasurement.report_id == rid)).all()
        assert report.status == "needs_review" and report.report_date == "2026-09-02"
        assert storage.retrieve_file(report.storage_key) == LAB        # original preserved, stored outside the DB
        assert extraction.owner_id == report.owner_id and "HbA1c" in extraction.text
        assert {c.test_name for c in cands} == {"HbA1c", "Hemoglobin", "LDL"}
        assert all(c.owner_id == report.owner_id for c in cands)
    listed = client.get("/api/v1/reports").json()[0]
    assert "storage_key" not in listed and "\\" not in json.dumps(listed)
    login(client, "other-owner@example.com")
    assert client.get(f"/api/v1/reports/{rid}/extraction").status_code == 404


def test_text_extraction_failure_marks_later_stages_not_reached(client):
    login(client, "textfail@example.com")
    rid = upload(client, b"%PDF-1.4 damaged").json()["id"]
    body, states, details = stage_states(client, rid)
    assert body["status"] == "failed"
    assert states == {"upload": "completed", "text_extraction": "failed", "ocr": "not_reached",
                      "structured_extraction": "not_reached", "save": "not_reached"}
    assert details["text_extraction"] == "The PDF could not be read. It may be damaged."


def test_ocr_unavailable_fails_the_ocr_stage(client, monkeypatch):
    login(client, "ocrmissing@example.com")
    monkeypatch.setattr(document_extraction, "ocr_available", lambda: False)
    rid = upload(client, text_pdf([])).json()["id"]
    body, states, _ = stage_states(client, rid)
    assert body["error_code"] == "ocr_unavailable"
    assert states["text_extraction"] == "completed" and states["ocr"] == "failed"
    assert states["structured_extraction"] == "not_reached"


def test_structured_extraction_failure_keeps_text_logs_safely_and_retries(client, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    login(client, "parsefail@example.com")
    real_parse = lab_parser.parse_report_text

    def broken(*args, **kwargs):
        raise ValueError(f"cannot parse {SECRET}")

    monkeypatch.setattr(lab_parser, "parse_report_text", broken)
    rid = upload(client).json()["id"]
    body, states, details = stage_states(client, rid)
    assert client.get(f"/api/v1/reports/{rid}").json()["status"] == "failed"
    assert body["error_code"] == "structured_extraction_failed"
    assert states == {"upload": "completed", "text_extraction": "completed", "ocr": "skipped",
                      "structured_extraction": "failed", "save": "not_reached"}
    assert details["structured_extraction"] == ("The report text was extracted, but structured measurements "
                                                "could not be created. You can retry processing.")
    assert "HbA1c (Glycosylated Hemoglobin) 6.2" in body["text"]           # extracted text is still available
    server_logs = [r for r in caplog.records if r.name.startswith("backend")]
    crash = [r.getMessage() for r in server_logs if "Structured extraction crashed" in r.getMessage()]
    assert crash and "error=ValueError" in crash[0] and "parse_report_text" in crash[0]   # observable
    assert all(SECRET not in r.getMessage() for r in server_logs)                         # no content
    assert "Traceback" not in json.dumps(body)

    monkeypatch.setattr(lab_parser, "parse_report_text", real_parse)
    assert client.post(f"/api/v1/reports/{rid}/extraction/retry").status_code == 200
    body, states, _ = stage_states(client, rid)
    assert body["status"] == "succeeded" and states["structured_extraction"] == "completed"


def test_persistence_failure_is_reported_as_save_stage(client, monkeypatch):
    login(client, "savefail@example.com")
    real_log = report_pipeline.log_action

    def failing_log(session, user_id, action, details=None):
        if action == "report_extraction_completed":
            raise OperationalError("INSERT", {}, Exception("disk I/O error"))
        return real_log(session, user_id, action, details)

    monkeypatch.setattr(report_pipeline, "log_action", failing_log)
    rid = upload(client).json()["id"]
    body, states, details = stage_states(client, rid)
    assert body["error_code"] == "persistence_failed"
    assert states["structured_extraction"] == "completed" and states["save"] == "failed"
    assert body["candidates"] == []               # the failed transaction left no partial rows
    assert "retry" in details["save"]


def test_processing_stage_states_while_running():
    ext = ReportExtraction(report_id=1, owner_id=1, status="processing", stage="text_extraction")
    assert [s["state"] for s in report_pipeline.stages(ext)] == [
        "completed", "active", "pending", "pending", "pending"]
    ext.stage, ext.method = "ocr", "ocr"
    assert [s["state"] for s in report_pipeline.stages(ext)] == [
        "completed", "completed", "active", "pending", "pending"]
    ext.stage, ext.method = "structured_extraction", "pdf_text"
    assert [s["state"] for s in report_pipeline.stages(ext)] == [
        "completed", "completed", "skipped", "active", "pending"]
    ext.stage, ext.method = "save", "pdf_text+ocr"
    assert [s["state"] for s in report_pipeline.stages(ext)] == [
        "completed", "completed", "completed", "completed", "active"]
    assert [s["state"] for s in report_pipeline.stages(None)] == [
        "completed", "pending", "pending", "pending", "pending"]


def test_ingestion_does_not_depend_on_text_ai(client, monkeypatch):
    login(client, "noai@example.com")
    calls = []

    def unavailable():
        calls.append(1)
        raise TextAIUnavailable("Ollama not running")

    monkeypatch.setattr(report_summary, "get_text_ai_provider", unavailable)
    rid = upload(client).json()["id"]
    assert calls == []                                            # upload/extraction never touch text AI
    for cand in client.get(f"/api/v1/reports/{rid}/extraction").json()["candidates"]:
        client.patch(f"/api/v1/reports/{rid}/candidates/{cand['id']}", json={"review_status": "accepted"})
    assert client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-09-02"}).status_code == 200
    assert calls == []
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    assert resp.status_code == 503 and "not available" in resp.json()["detail"]
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert report["status"] == "confirmed"                        # processed; only the summary is unavailable
    assert len(client.get("/api/v1/measurements").json()) == 3
    assert client.get(f"/api/v1/reports/{rid}/summary").json() is None


def test_parser_handles_ocr_text_without_spaces():
    ocr_text = "\n".join([
        "--- Page 1 ---",
        "SampleCollectedOn:02-Sep-202608:15  ReportDate:02/09/2026",
        "HbA1c(Glycosylated Hemoglobin)  6.2H  %  4.0-5.6",
        "FastingBloodGlucose  112H  mg/dL  70-99",
        "Total LeucocyteCount  7.9  x10^3/uL  4.0-11.0",
        "SerumCreatinine  0.94  mg/dL  0.70-1.30",
        "LDLCholesterol  138H  mg/dL  <100",
        "BloodPressure:124/80mmHg",
    ])
    result = lab_parser.parse_report_text(ocr_text, ocr=True)
    assert result.document_date == "2026-09-02"
    got = {c.test_name: (c.value, c.flag) for c in result.candidates}
    assert got == {"HbA1c": (6.2, "high"), "Glucose (fasting)": (112, "high"), "WBC": (7.9, "unknown"),
                   "Creatinine": (0.94, "unknown"), "LDL": (138, "high"),
                   "Blood Pressure (systolic)": (124, "unknown"), "Blood Pressure (diastolic)": (80, "unknown")}
    assert all(c.confidence != "high" for c in result.candidates)
    # compact matching must not create false canonical names
    assert lab_parser.canonical_name("RandomGlucose") is None
    assert lab_parser.canonical_name("Serum") is None
    assert lab_parser.canonical_name("TotalCholesterol") is None


def test_schema_drift_is_detected():
    import backend.models  # noqa: F401  (register all tables)
    old = sa_create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(old)
    assert missing_columns(old) == []
    with old.begin() as conn:
        conn.execute(text("ALTER TABLE reportextraction DROP COLUMN stage"))
    assert missing_columns(old) == ["reportextraction.stage"]
