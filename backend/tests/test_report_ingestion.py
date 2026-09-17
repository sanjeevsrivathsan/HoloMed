"""Medical report ingestion: upload → extraction → review → canonical data → summary/search."""
import io
import json
import logging
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.database import get_session
from backend.main import app
from backend.models import AuditLog, ExtractedMeasurement, MedicalMeasurement, Report, ReportExtraction, \
    SourceReference
from backend.routers import report as report_router
from backend.routers import search as search_router
from backend.services import document_extraction, lab_parser, storage
from backend.services.explanation import report_summary
from backend.services.synthetic_pdf import text_pdf
from backend.services.text_ai.providers import Completion, TextAIUnavailable

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

LAB_LINES = [
    "SYNTHETIC TEST LAB - NOT REAL PATIENT DATA",
    "Collected: 2026-03-14",
    "HbA1c 7.9 % 4.0 - 5.6 H",
    "Hemoglobin 12.1 g/dL 13.0 - 17.0 L",
    "WBC Count 7.2 x10^3/uL 4.0 - 11.0",
    "Fasting Blood Glucose 131 mg/dL 70 - 99 H",
    "Serum Creatinine 0.93 mg/dL 0.70 - 1.30",
    "LDL Cholesterol 162 mg/dL <100 H",
    "HDL Cholesterol 38 mg/dL >40 L",
    "Blood Pressure: 131/86 mmHg",
]
SECRET_MARKER = "Zyxwvut-Private-Remark"


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


def login(client: TestClient, email: str):
    client.cookies.clear()
    client.post("/api/v1/auth/register", params={"email": email, "password": "password123"})
    resp = client.post("/api/v1/auth/login", data={"username": email, "password": "password123"})
    assert resp.status_code == 200


def upload(client, content: bytes, name="lab.pdf", type_="Blood Test", **data):
    return client.post("/api/v1/reports", files={"file": (name, content, "application/pdf")},
                       data={"type": type_, **data})


def lab_pdf(extra=()):
    return text_pdf(LAB_LINES + list(extra))


def png_of(lines):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1200, 80 + 75 * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    for i, line in enumerate(lines):
        draw.text((40, 30 + i * 75), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return img, buf.getvalue()


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def complete_json(self, system, user, schema, max_tokens, temperature):
        self.prompts.append(user)
        return Completion(text=json.dumps(self.payloads.pop(0)), model=self.model)


SAFE = {"overview": "This blood test report lists HbA1c, LDL and HDL results.",
        "terms": ["HbA1c: a blood test that reflects average blood sugar over recent months."],
        "questions": ["What do these results mean for me?"]}


# ── Upload validation ──────────────────────────────────────────────────────────

def test_upload_requires_auth(client, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "not_testsecret")   # disable the test-only anonymous fallback
    client.cookies.clear()
    assert upload(client, lab_pdf()).status_code == 401


def test_capabilities(client):
    login(client, "caps@example.com")
    body = client.get("/api/v1/reports/capabilities").json()
    labels = [f["label"] for f in body["formats"]]
    assert "PDF" in labels
    assert ("PNG image" in labels) == document_extraction.ocr_available()
    assert body["max_bytes"] == 50 * 1024 * 1024
    assert [t["label"] for t in body["document_types"]] == [
        "Blood Test / Laboratory Report", "Radiology Report", "Discharge Summary", "Clinical Note",
        "Prescription", "Other"]


def test_upload_rejects_unsupported_empty_oversized_and_unknown_type(client, monkeypatch):
    login(client, "val@example.com")
    resp = client.post("/api/v1/reports", files={"file": ("notes.txt", b"HbA1c 7.0 %", "text/plain")})
    assert resp.status_code == 415
    # the declared content type is not trusted: a disguised text file is still rejected
    assert upload(client, b"GIF89a....", name="x.pdf").status_code == 415
    assert upload(client, b"").status_code == 400
    assert upload(client, lab_pdf(), type_="Astrology").status_code == 422
    monkeypatch.setattr(report_router, "MAX_REPORT_BYTES", 100)
    assert upload(client, lab_pdf()).status_code == 413
    assert client.get("/api/v1/reports").json() == []


# ── Extraction + parsing ───────────────────────────────────────────────────────

def test_blood_test_upload_extracts_candidates(client):
    login(client, "lab@example.com")
    resp = upload(client, lab_pdf(), title="March labs", laboratory="Synthetic Lab")
    assert resp.status_code == 200
    body = resp.json()
    assert "storage_key" not in body and body["mime_type"] == "application/pdf"
    rid = body["id"]

    reports = client.get("/api/v1/reports").json()
    assert reports[0]["status"] == "needs_review"
    assert reports[0]["extraction_status"] == "succeeded"
    assert reports[0]["candidate_count"] == 9 and reports[0]["measurement_count"] == 0
    assert reports[0]["report_date"] == "2026-03-14"   # printed date replaces the upload-time placeholder
    explicit = upload(client, lab_pdf(), report_date="2026-03-20").json()["id"]
    assert client.get(f"/api/v1/reports/{explicit}").json()["report_date"] == "2026-03-20"

    ex = client.get(f"/api/v1/reports/{rid}/extraction").json()
    assert ex["method"] == "pdf_text" and ex["quality"] == "good" and ex["page_count"] == 1
    assert "HbA1c 7.9 %" in ex["text"]
    assert ex["document_date"] == "2026-03-14"
    assert set(ex["timings"]) >= {"pdf_text_ms", "parse_ms", "total_ms"}
    by_name = {c["test_name"]: c for c in ex["candidates"]}
    assert set(by_name) == {"HbA1c", "Hemoglobin", "WBC", "Glucose (fasting)", "Creatinine", "LDL", "HDL",
                            "Blood Pressure (systolic)", "Blood Pressure (diastolic)"}
    hba1c = by_name["HbA1c"]
    assert (hba1c["value"], hba1c["unit"], hba1c["reference_range"], hba1c["flag"]) == (7.9, "%", "4.0 - 5.6", "high")
    assert hba1c["page"] == 1 and hba1c["review_status"] == "pending" and hba1c["confidence"] == "high"
    assert by_name["Hemoglobin"]["flag"] == "low"
    # no printed flag → no flag is invented
    assert by_name["WBC"]["flag"] == "unknown"
    assert by_name["Blood Pressure (systolic)"]["value"] == 131
    assert by_name["Blood Pressure (diastolic)"]["reference_range"] is None

    with Session(engine) as s:
        # the original is stored unchanged and a document source reference exists
        report = s.get(Report, rid)
        assert storage.retrieve_file(report.storage_key) == lab_pdf()
        ref = s.exec(select(SourceReference).where(SourceReference.report_id == str(rid))).one()
        assert ref.storage_location == f"report:{rid}" and "\\" not in ref.storage_location
        actions = [a.action for a in s.exec(select(AuditLog)).all()]
        assert {"report_uploaded", "report_extraction_completed"} <= set(actions)


def test_damaged_pdf_fails_cleanly_and_can_be_retried(client):
    login(client, "fail@example.com")
    rid = upload(client, b"%PDF-1.4 truncated").json()["id"]
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert report["status"] == "failed"
    ex = client.get(f"/api/v1/reports/{rid}/extraction").json()
    assert ex["error_code"] == "pdf_unreadable"
    assert ex["warnings"][0] == "The PDF could not be read. It may be damaged."
    resp = client.post(f"/api/v1/reports/{rid}/extraction/retry")
    assert resp.status_code == 200
    assert client.get(f"/api/v1/reports/{rid}").json()["status"] == "failed"
    # the original stays downloadable
    assert client.get(f"/api/v1/reports/{rid}/download").content == b"%PDF-1.4 truncated"


def test_non_lab_document_is_extracted_without_review_values(client):
    login(client, "note@example.com")
    pdf = text_pdf(["Discharge summary (synthetic)", "Admitted for observation and discharged the next day.",
                    "Follow up with the clinic as arranged."])
    rid = upload(client, pdf, type_="Discharge Summary").json()["id"]
    assert client.get(f"/api/v1/reports/{rid}").json()["status"] == "extracted"
    ex = client.get(f"/api/v1/reports/{rid}/extraction").json()
    assert ex["candidates"] == [] and "Admitted for observation" in ex["text"]


def test_text_less_pdf_without_ocr_reports_limitation(client, monkeypatch):
    login(client, "noocr@example.com")
    monkeypatch.setattr(document_extraction, "ocr_available", lambda: False)
    rid = upload(client, text_pdf([])).json()["id"]
    ex = client.get(f"/api/v1/reports/{rid}/extraction").json()
    assert ex["status"] == "failed" and ex["error_code"] == "ocr_unavailable"
    # images are not offered or accepted without OCR
    _, png = png_of(["x"])
    assert client.post("/api/v1/reports", files={"file": ("a.png", png, "image/png")}).status_code == 415


@pytest.mark.skipif(not document_extraction.ocr_available(), reason="optional OCR stack not installed")
def test_ocr_fallback_for_images_and_scanned_pdfs(client):
    login(client, "ocr@example.com")
    img, png = png_of(["Collected: 2025-06-01", "HbA1c 6.4 % 4.0 - 5.6 H", "Serum Creatinine 1.1 mg/dL 0.7 - 1.3"])
    resp = client.post("/api/v1/reports", files={"file": ("scan.png", png, "image/png")},
                       data={"type": "Blood Test"})
    assert resp.status_code == 200 and resp.json()["mime_type"] == "image/png"
    ex = client.get(f"/api/v1/reports/{resp.json()['id']}/extraction").json()
    assert ex["method"] == "ocr" and ex["quality"] == "low"
    assert any("OCR" in w for w in ex["warnings"])
    by_name = {c["test_name"]: c for c in ex["candidates"]}
    assert by_name["HbA1c"]["value"] == 6.4 and by_name["HbA1c"]["flag"] == "high"
    # OCR output is never reported with high confidence
    assert all(c["confidence"] != "high" for c in ex["candidates"])

    buf = io.BytesIO()
    img.save(buf, "PDF")
    rid = upload(client, buf.getvalue(), name="scanned.pdf").json()["id"]
    ex = client.get(f"/api/v1/reports/{rid}/extraction").json()
    assert ex["method"] == "ocr" and "ocr_ms" in ex["timings"]
    assert {c["test_name"] for c in ex["candidates"]} >= {"HbA1c", "Creatinine"}


def test_parser_units():
    assert lab_parser.canonical_name("Glycated Haemoglobin (HPLC)") == "HbA1c"
    assert lab_parser.canonical_name("Hb") == "Hemoglobin"
    assert lab_parser.canonical_name("Total Leucocyte Count") == "WBC"
    assert lab_parser.canonical_name("FBS") == "Glucose (fasting)"
    assert lab_parser.canonical_name("Random Glucose") is None
    assert lab_parser.canonical_name("Platelet Count") is None
    result = lab_parser.parse_report_text(
        "Age 45 Years\nPage 1 of 2\nPlatelet Count 250 x10^3/uL 150 - 400\nVitamin D 22\nHbA1c 45 %\n"
        "Report Date: 03/04/2025")
    names = [c.test_name for c in result.candidates]
    # unrecognised analytes are offered only with a printed range; noise lines are skipped
    assert names == ["Platelet Count", "HbA1c"]
    # implausible value for the unit → low confidence instead of a guess
    assert result.candidates[1].confidence == "low"
    # day/month order is never guessed
    assert result.document_date is None and "unambiguously" in result.warnings[0]
    assert lab_parser.parse_date("13/04/2025") == (date(2025, 4, 13), False)
    assert lab_parser.parse_date("14 Mar 2026") == (date(2026, 3, 14), False)


# ── Review + canonical measurements ────────────────────────────────────────────

def _candidates(client, rid):
    return {c["test_name"]: c for c in client.get(f"/api/v1/reports/{rid}/extraction").json()["candidates"]}


def test_review_edit_reject_confirm_creates_canonical_measurements(client):
    login(client, "review@example.com")
    rid = upload(client, lab_pdf(), laboratory="Synthetic Lab").json()["id"]
    cands = _candidates(client, rid)
    url = f"/api/v1/reports/{rid}/candidates"

    # summaries wait for review
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"}).status_code == 409

    resp = client.patch(f"{url}/{cands['HbA1c']['id']}", json={"value": 7.8, "review_status": "accepted"})
    assert resp.status_code == 200 and resp.json()["edited"] is True and resp.json()["value_text"] == "7.8"
    for name in ("Hemoglobin", "LDL", "Blood Pressure (systolic)"):
        client.patch(f"{url}/{cands[name]['id']}", json={"review_status": "accepted"})
    client.patch(f"{url}/{cands['WBC']['id']}", json={"review_status": "rejected"})
    assert client.patch(f"{url}/{cands['HDL']['id']}", json={"flag": "invented"}).status_code == 422
    assert client.patch(f"{url}/999999", json={"review_status": "accepted"}).status_code == 404

    resp = client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-03-14"})
    assert resp.status_code == 200
    assert resp.json() == {"report_id": rid, "status": "confirmed", "review_status": "confirmed",
                           "measurements_created": 4}

    meas = client.get("/api/v1/measurements").json()
    assert sorted(m["test_name"] for m in meas) == ["Blood Pressure (systolic)", "HbA1c", "Hemoglobin", "LDL"]
    hba1c = next(m for m in meas if m["test_name"] == "HbA1c")
    assert hba1c["value"] == 7.8 and hba1c["report_id"] == rid and hba1c["report_date"] == "2026-03-14"
    assert hba1c["flag"] == "high" and hba1c["reference_range"] == "4.0 - 5.6"
    assert hba1c["source_location"] == "Page 1" and hba1c["laboratory"] == "Synthetic Lab"
    assert hba1c["comments"] == "Edited during review"

    after = _candidates(client, rid)
    assert after["HbA1c"]["review_status"] == "confirmed" and after["HbA1c"]["measurement_id"] == hba1c["id"]
    assert after["WBC"]["review_status"] == "rejected"
    assert after["HDL"]["review_status"] == "rejected"   # never accepted → not saved
    # confirmed values are immutable and retry is refused once confirmed
    assert client.patch(f"{url}/{after['HbA1c']['id']}", json={"value": 1}).status_code == 409
    assert client.post(f"/api/v1/reports/{rid}/extraction/retry").status_code == 409

    listed = client.get("/api/v1/reports").json()[0]
    assert listed["measurement_count"] == 4 and listed["report_date"] == "2026-03-14"


def test_confirm_requires_values(client):
    login(client, "missing@example.com")
    rid = upload(client, lab_pdf()).json()["id"]
    cand = _candidates(client, rid)["HbA1c"]
    client.patch(f"/api/v1/reports/{rid}/candidates/{cand['id']}", json={"value": None, "review_status": "accepted"})
    resp = client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-03-14"})
    assert resp.status_code == 422
    assert client.get("/api/v1/measurements").json() == []
    assert client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "not-a-date"}).status_code == 422


def test_other_users_cannot_access_report_artifacts(client):
    login(client, "owner@example.com")
    rid = upload(client, lab_pdf()).json()["id"]
    cid = next(iter(_candidates(client, rid).values()))["id"]
    login(client, "intruder@example.com")
    assert client.get(f"/api/v1/reports/{rid}/extraction").status_code == 404
    assert client.patch(f"/api/v1/reports/{rid}/candidates/{cid}", json={"review_status": "accepted"}).status_code == 404
    assert client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-01-01"}).status_code == 404
    assert client.post(f"/api/v1/reports/{rid}/extraction/retry").status_code == 404
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"}).status_code == 404
    assert client.get("/api/v1/reports").json() == []
    assert client.post("/api/v1/search", json={"query": "HbA1c"}).json()["report_ids"] == []
    # the intruder's own upload cannot reach the owner's candidate
    other = upload(client, lab_pdf()).json()["id"]
    assert client.patch(f"/api/v1/reports/{other}/candidates/{cid}", json={"review_status": "accepted"}).status_code == 404


def test_delete_removes_derived_artifacts(client):
    login(client, "delete@example.com")
    rid = upload(client, lab_pdf()).json()["id"]
    cand = _candidates(client, rid)["HbA1c"]
    client.patch(f"/api/v1/reports/{rid}/candidates/{cand['id']}", json={"review_status": "accepted"})
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-03-14"})
    assert client.delete(f"/api/v1/reports/{rid}").status_code == 200
    with Session(engine) as s:
        assert s.exec(select(ReportExtraction)).all() == []
        assert s.exec(select(ExtractedMeasurement)).all() == []
        assert s.exec(select(MedicalMeasurement)).all() == []
        assert s.exec(select(SourceReference)).all() == []


# ── Summary ────────────────────────────────────────────────────────────────────

def _confirmed_report(client):
    rid = upload(client, lab_pdf()).json()["id"]
    for cand in _candidates(client, rid).values():
        if cand["test_name"] in ("HbA1c", "WBC", "LDL"):
            client.patch(f"/api/v1/reports/{rid}/candidates/{cand['id']}", json={"review_status": "accepted"})
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-03-14"})
    return rid


def test_summary_uses_confirmed_values_and_marks_completion(client, monkeypatch):
    login(client, "summary@example.com")
    rid = _confirmed_report(client)
    provider = FakeProvider([SAFE])
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: provider)
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["safety_message"] == ("AI-generated information — not a diagnosis. "
                                      "Consult a qualified healthcare professional.")
    sections = {s["key"]: s["content"] for s in json.loads(body["sections"])}
    assert list(sections) == ["overview", "executive", "findings", "abnormal", "terms", "questions", "limitations"]
    assert all(s["source"] == ("ai" if s["key"] in ("executive", "terms", "questions") else "data")
               for s in json.loads(body["sections"]))
    assert "3 confirmed result(s)" in sections["overview"]
    assert sections["executive"] == SAFE["overview"]
    # flagged section is built from printed flags only
    assert "HbA1c: 7.9 %" in sections["abnormal"] and "LDL: 162 mg/dL" in sections["abnormal"]
    assert "WBC" not in sections["abnormal"] and "does not judge" in sections["abnormal"]
    # the model only sees confirmed values, never the raw document
    prompt = provider.prompts[0]
    assert "HbA1c" in prompt and "Hemoglobin" not in prompt and "document_text" not in prompt
    assert "4.0 - 5.6" not in prompt and "<100" not in prompt            # printed ranges are not sent
    assert prompt.count('"report_flag": "marked high by the laboratory"') == 2  # HbA1c and LDL only
    report = client.get(f"/api/v1/reports/{rid}").json()
    # a summary does not change the review state ("completed" is no longer used)
    assert (report["status"], report["processing_status"], report["review_status"]) ==         ("confirmed", "processed", "confirmed")
    assert client.get(f"/api/v1/reports/{rid}/summary").json()["safety_message"].startswith("AI-generated")
    assert client.get("/api/v1/reports").json()[0]["summary"]["mode"] == "standard"


def test_summary_rejects_unsafe_output(client, monkeypatch):
    login(client, "unsafe@example.com")
    rid = _confirmed_report(client)
    unsafe = [
        {**SAFE, "overview": "These results suggest diabetes."},
        {**SAFE, "overview": "Your HbA1c is elevated."},
        {**SAFE, "questions": ["Should I start metformin?"]},
        {**SAFE, "overview": "The report shows an HbA1c of 9.4."},
        {**SAFE, "overview": "The patient has a problem."},
        {**SAFE, "overview": "This confirms the diagnosis of a disorder."},
    ]
    for payload in unsafe:
        monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda p=payload: FakeProvider([p, p]))
        resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
        assert resp.status_code == 502, payload
    assert client.get(f"/api/v1/reports/{rid}/summary").json() is None
    assert client.get(f"/api/v1/reports/{rid}").json()["status"] == "confirmed"

    # a safe retry after a rejected first answer succeeds
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: FakeProvider([unsafe[0], SAFE]))
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "quick"}).status_code == 200


def test_summary_safety_filter_allows_neutral_text():
    ok = ("HbA1c: a blood test that reflects average blood sugar over recent months. "
          "LDL (low-density lipoprotein) and HDL (high-density lipoprotein) are cholesterol measures. "
          "White blood cells help fight infections. This is not a diagnosis.")
    assert report_summary.safety_violations(ok, []) == []
    assert report_summary.safety_violations("HbA1c was 7.9 on 2026-03-14", ["7.9", "2026", "03", "14"]) == []
    assert "unsupported-number" in report_summary.safety_violations("HbA1c was 8.1", ["7.9"])


def test_summary_provider_unavailable(client, monkeypatch):
    login(client, "down@example.com")
    rid = _confirmed_report(client)

    class Down:
        name, model = "down", "none"

        def complete_json(self, *args):
            raise TextAIUnavailable("unreachable")

    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: Down())
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    assert resp.status_code == 503 and "not available" in resp.json()["detail"]
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "poetry"}).status_code == 422


def test_non_lab_summary_uses_extracted_text(client, monkeypatch):
    login(client, "textsum@example.com")
    pdf = text_pdf(["Clinical note (synthetic)", "Seen in clinic for a routine visit on 2026-02-02."])
    rid = upload(client, pdf, type_="Clinical Note").json()["id"]
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-02-02"})
    provider = FakeProvider([{"overview": "This clinical note describes a routine clinic visit.",
                              "terms": ["Clinic visit: an outpatient appointment."],
                              "questions": ["Is any follow-up planned?"]}])
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: provider)
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "detailed"})
    assert resp.status_code == 200
    assert [s["key"] for s in json.loads(resp.json()["sections"])] == [
        "overview", "executive", "terms", "questions", "limitations"]
    assert "routine visit" in provider.prompts[0]


# ── Search / timeline data ─────────────────────────────────────────────────────

def test_structured_search_over_canonical_measurements(client):
    login(client, "search2@example.com")
    assert client.post("/api/v1/demo/load").status_code == 200
    assert client.post("/api/v1/demo/load").status_code == 409

    res = client.post("/api/v1/search", json={"query": "Show HbA1c results from the last two years"}).json()
    assert res["interpretation"]["tests"] == ["HbA1c"]
    assert res["interpretation"]["since"] == (date.today() - timedelta(days=730)).isoformat()
    meas = {m["id"]: m for m in client.get("/api/v1/measurements").json()}
    found = [meas[i] for i in res["measurement_ids"]]
    assert [m["value"] for m in found] == [6.1, 5.8]   # oldest first; the newest report is still in review
    assert all(m["test_name"] == "HbA1c" for m in found)
    assert set(res["report_ids"]) == {m["report_id"] for m in found}

    res = client.post("/api/v1/search", json={"query": "HbA1c in the last month"}).json()
    assert res["measurement_ids"] == []

    res = client.post("/api/v1/search", json={"query": "flagged cholesterol"}).json()
    assert {meas[i]["test_name"] for i in res["measurement_ids"]} == {"LDL"}
    res = client.post("/api/v1/search", json={"query": "HDL"}).json()
    assert {meas[i]["test_name"] for i in res["measurement_ids"]} == {"HDL"}
    res = client.post("/api/v1/search", json={"query": "blood pressure"}).json()
    assert {meas[i]["test_name"] for i in res["measurement_ids"]} == {
        "Blood Pressure (systolic)", "Blood Pressure (diastolic)"}
    res = client.post("/api/v1/search", json={"query": "blood tests"}).json()
    assert len(res["report_ids"]) == 3 and res["measurement_ids"] == []
    res = client.post("/api/v1/search", json={"query": "radiology"}).json()
    assert res["report_ids"] == []
    res = client.post("/api/v1/search", json={"query": "Demo Laboratory"}).json()
    assert len(res["report_ids"]) == 3


def test_search_interpretation():
    today = date(2026, 9, 17)
    spec = search_router.interpret("low haemoglobin since 2024", today)
    assert spec.tests == ["Hemoglobin"] and spec.flags == ["low"] and spec.since == date(2024, 1, 1)
    spec = search_router.interpret("LDL (low-density lipoprotein) in 2025", today)
    assert spec.tests == ["LDL"] and spec.flags == [] and spec.until == date(2025, 12, 31)
    assert search_router.interpret("HbA1c", today).tests == ["HbA1c"]
    assert search_router.interpret("fasting sugar past 6 months", today).since == date(2026, 3, 18)


def test_demo_data_is_labelled_and_removable(client):
    login(client, "demo@example.com")
    assert client.get("/api/v1/demo").json()["loaded"] is False
    ids = client.post("/api/v1/demo/load").json()["report_ids"]
    reports = client.get("/api/v1/reports").json()
    assert len(reports) == 3
    assert all(r["source"] == "HoloMed demo (synthetic)" and "synthetic" in r["title"] for r in reports)
    assert sorted(r["status"] for r in reports) == ["confirmed", "confirmed", "needs_review"]
    text = client.get(f"/api/v1/reports/{ids[0]}/extraction").json()["text"]
    assert "SYNTHETIC DEMONSTRATION REPORT - NOT REAL PATIENT DATA" in text
    names = {m["test_name"] for m in client.get("/api/v1/measurements").json()}
    assert names == {"HbA1c", "LDL", "HDL", "Hemoglobin", "WBC", "Glucose (fasting)", "Creatinine",
                     "Blood Pressure (systolic)", "Blood Pressure (diastolic)"}
    removed = client.delete("/api/v1/demo").json()
    assert removed == {"loaded": False, "removed": 3}
    assert client.get("/api/v1/reports").json() == []
    assert client.get("/api/v1/measurements").json() == []


# ── Logging hygiene ────────────────────────────────────────────────────────────

def test_no_document_content_in_logs(client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    login(client, "logs@example.com")
    rid = upload(client, lab_pdf([f"Comment: {SECRET_MARKER}"]), title="Private title").json()["id"]
    for cand in _candidates(client, rid).values():
        client.patch(f"/api/v1/reports/{rid}/candidates/{cand['id']}", json={"review_status": "accepted"})
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"report_date": "2026-03-14"})
    unsafe = {**SAFE, "overview": f"{SECRET_MARKER} suggests diabetes."}
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: FakeProvider([unsafe, unsafe]))
    client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    upload(client, b"%PDF-1.4 " + SECRET_MARKER.encode())
    # server-side loggers only (the test client logs its own request URLs)
    logged = " | ".join(r.getMessage() for r in caplog.records if r.name.startswith(("backend", "uvicorn", "pypdf")))
    for forbidden in (SECRET_MARKER, "7.9", "HbA1c", "Private title", "password123"):
        assert forbidden not in logged
    with Session(engine) as s:
        details = " ".join(a.details or "" for a in s.exec(select(AuditLog)).all())
    assert SECRET_MARKER not in details and "Private title" not in details and "HbA1c" not in details


def test_text_ai_status_reports_state_without_details(client, monkeypatch):
    import httpx
    from backend import config
    login(client, "aistatus@example.com")

    async def refuse(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", refuse)
    body = client.get("/api/v1/ai/status").json()
    assert body["provider"] == "ollama" and body["status"] == "not_running"
    assert "localhost" not in json.dumps(body)

    async def tags(self, url, *args, **kwargs):
        return httpx.Response(200, json={"models": [{"name": body["model"]}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", tags)
    assert client.get("/api/v1/ai/status").json()["status"] == "connected"

    monkeypatch.setattr(config, "TEXT_AI_PROVIDER", "omniroute")
    monkeypatch.setattr(config, "OMNIROUTE_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "")
    body = client.get("/api/v1/ai/status").json()
    assert body == {"provider": "omniroute", "model": None, "status": "not_configured"}
    monkeypatch.setattr(config, "OMNIROUTE_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setattr(config, "OMNIROUTE_MODEL", "some-model")
    body = client.get("/api/v1/ai/status").json()
    assert body["status"] == "configured" and "sk-test" not in json.dumps(body) and "gateway" not in json.dumps(body)
