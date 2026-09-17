"""Phase 7B: realistic report ingestion via the API, report-date confirmation, per-value review,
status model, structured summaries (modes, trends, limitations), search and isolation."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from backend.database import get_session
from backend.main import app
from backend.models import MedicalMeasurement, Report
from backend.services import storage
from backend.services.explanation import report_summary
from backend.services.synthetic_pdf import text_pdf, text_pdf_pages
from backend.services.text_ai.providers import Completion, TextAIUnavailable
from backend.tests.synthetic_reports import BLOCK_PAGES

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
REALISTIC = text_pdf_pages(BLOCK_PAGES)
AMBIGUOUS = text_pdf([
    "SYNTHETIC LAB - NOT REAL PATIENT DATA",
    "Registration Time : 05/09/2026 8:05AM Collected on : 05/09/2026 8:40AM",
    "Test Results Units Reference Range",
    "HDL Cholesterol",
    "Method: Direct",
    "44.0 mg/dL 40 - 60",
])


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


def upload(client, content, name="Lab_Report.pdf", type_="Blood Test"):
    resp = client.post("/api/v1/reports", files={"file": (name, content, "application/pdf")}, data={"type": type_})
    assert resp.status_code == 200
    return resp.json()["id"]


def extraction(client, rid):
    return client.get(f"/api/v1/reports/{rid}/extraction").json()


def cands(client, rid):
    return {c["test_name"]: c for c in extraction(client, rid)["candidates"]}


class Provider:
    name, model = "fake", "fake-model"

    def __init__(self, payload=None):
        self.payload = payload or {
            "overview": "This blood test report from 14 Sep 2026 contains a lipid profile, liver function tests "
                        "and blood glucose tests. The laboratory marked fasting glucose and HbA1c high.",
            "terms": ["HDL: a measure of high-density lipoprotein cholesterol.",
                      "Bilirubin: a substance measured to look at how bile is processed."],
            "questions": ["What do my HDL and LDL results mean together?",
                          "Why did the laboratory mark my HbA1c result?"],
        }
        self.calls = []

    def complete_json(self, system, user, schema, max_tokens, temperature):
        self.calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        return Completion(text=json.dumps(self.payload), model=self.model)


def test_realistic_report_produces_candidates_and_date_candidates(client):
    login(client, "real@example.com")
    rid = upload(client, REALISTIC)
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["processing_status"], report["review_status"]) == ("processed", "needs_review")
    assert report["detected_count"] == 22 and report["confirmed_count"] == 0 and report["pending_count"] == 22
    # detected date is provisional and clearly unconfirmed
    assert (report["report_date"], report["date_source"], report["date_confirmed"], report["detected_date"]) == \
        ("2026-09-14", "extracted", False, "2026-09-14")
    ex = extraction(client, rid)
    assert [(d["kind"], d["label"], d["value"]) for d in ex["date_candidates"]] == [
        ("collected", "Collected on", "2026-09-14"), ("registered", "Registration Time", "2026-09-13"),
        ("reported", "Reported on", "2026-09-15")]
    by_name = cands(client, rid)
    assert by_name["HDL"]["reference_range"] == "Desirable > 40.0; Higher Risk < 40.0"
    assert len(by_name["LDL"]["reference_range"]) > 80          # long printed tiers are stored
    # editing a candidate with a long printed range round-trips (limit raised to 200)
    resp = client.patch(f"/api/v1/reports/{rid}/candidates/{by_name['LDL']['id']}",
                        json={"reference_range": by_name["LDL"]["reference_range"], "unit": "mg/dL"})
    assert resp.status_code == 200 and resp.json()["edited"] is False


def test_ambiguous_dates_require_a_user_choice(client):
    login(client, "ambiguous@example.com")
    rid = upload(client, AMBIGUOUS)
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert report["date_source"] == "upload_default" and report["date_confirmed"] is False
    assert report["detected_date"] is None
    ex = extraction(client, rid)
    assert ex["date_candidates"][0]["alternatives"] == ["2026-09-05", "2026-05-09"]
    assert any("choose it during review" in w for w in ex["warnings"])
    # choosing one of the detected readings counts as "extracted"
    resp = client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-05"})
    assert resp.status_code == 200
    assert (resp.json()["date_source"], resp.json()["date_confirmed"], resp.json()["report_date"]) == \
        ("extracted", True, "2026-09-05")


def test_date_confirmation_provenance_and_per_value_confirmation(client):
    login(client, "review7b@example.com")
    rid = upload(client, REALISTIC)
    by_name = cands(client, rid)
    url = f"/api/v1/reports/{rid}/candidates"
    # values cannot be confirmed before the report date
    resp = client.post(f"{url}/{by_name['HDL']['id']}/confirm")
    assert resp.status_code == 409 and resp.json()["detail"] == "Confirm the report date first."
    assert client.get("/api/v1/measurements").json() == []

    # the user overrides the detected date
    resp = client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-16"})
    body = resp.json()
    assert (body["date_source"], body["date_confirmed"], body["detected_date"], body["report_date"]) == \
        ("user_override", True, "2026-09-14", "2026-09-16")
    assert body["review_status"] == "needs_review"

    # confirm one value: becomes canonical immediately; report is partially confirmed
    resp = client.post(f"{url}/{by_name['HDL']['id']}/confirm")
    assert resp.status_code == 200 and resp.json()["review_status"] == "confirmed"
    meas = client.get("/api/v1/measurements").json()
    assert [(m["test_name"], m["value"], m["report_date"], m["report_id"], m["source_location"]) for m in meas] == \
        [("HDL", 41.2, "2026-09-16", rid, "Page 1")]
    assert meas[0]["reference_range"] == "Desirable > 40.0; Higher Risk < 40.0" and meas[0]["flag"] == "unknown"
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["status"], report["review_status"], report["confirmed_count"], report["pending_count"]) == \
        ("partially_confirmed", "partially_confirmed", 1, 21)
    assert client.post(f"{url}/{by_name['HDL']['id']}/confirm").status_code == 409     # already confirmed

    # ignore one, confirm a few by id, leaving the rest pending
    client.patch(f"{url}/{by_name['VLDL']['id']}", json={"review_status": "rejected"})
    assert client.post(f"{url}/{by_name['VLDL']['id']}/confirm").status_code == 409     # ignored
    ids = [by_name[n]["id"] for n in ("LDL", "HbA1c", "Glucose (fasting)")]
    resp = client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": ids})
    assert resp.json()["measurements_created"] == 3 and resp.json()["review_status"] == "partially_confirmed"
    assert client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": [999999]}).status_code == 409

    # changing the date later moves every confirmed value
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    assert {m["report_date"] for m in client.get("/api/v1/measurements").json()} == {"2026-09-14"}
    assert client.get(f"/api/v1/reports/{rid}").json()["date_source"] == "extracted"

    # confirm all remaining → fully confirmed; retry is no longer allowed
    remaining = [c["id"] for c in extraction(client, rid)["candidates"] if c["review_status"] == "pending"]
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": remaining})
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["review_status"], report["confirmed_count"], report["pending_count"], report["ignored_count"]) == \
        ("confirmed", 21, 0, 1)
    assert client.post(f"/api/v1/reports/{rid}/extraction/retry").status_code == 409


def test_confirming_the_date_only_completes_a_report_without_values(client):
    login(client, "novalues@example.com")
    rid = upload(client, text_pdf(["Clinical note (synthetic)", "Seen for a routine visit.",
                                   "Date: 2026-02-02"]), type_="Clinical Note")
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["status"], report["review_status"], report["detected_count"]) == ("extracted", "needs_review", 0)
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-02-02"})
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["status"], report["review_status"]) == ("confirmed", "confirmed")


def test_status_model_for_processing_failure_and_legacy_rows(client):
    login(client, "status@example.com")
    rid = upload(client, b"%PDF-1.4 broken")
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert (report["processing_status"], report["review_status"]) == ("failed", None)
    with Session(engine) as s:
        user_id = s.get(Report, rid).owner_id
        for status in ("ready", "completed"):
            s.add(Report(owner_id=user_id, title=f"legacy {status}", status=status, original_filename="x.pdf",
                         mime_type="application/pdf", file_size=1, storage_key="k"))
        s.commit()
    listed = {r["title"]: r for r in client.get("/api/v1/reports").json()}
    for status in ("ready", "completed"):
        r = listed[f"legacy {status}"]
        assert (r["processing_status"], r["review_status"], r["date_confirmed"]) == ("processed", "confirmed", True)
    assert listed["legacy ready"]["status"] == "completed"


def test_summary_needs_confirmed_values_and_uses_structured_data(client, monkeypatch):
    login(client, "summary7b@example.com")
    rid = upload(client, REALISTIC)
    provider = Provider()
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: provider)
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    assert resp.status_code == 409 and "Confirm at least one" in resp.json()["detail"]
    assert provider.calls == []

    by_name = cands(client, rid)
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    ids = [by_name[n]["id"] for n in ("HDL", "LDL", "Glucose (fasting)", "HbA1c", "Bilirubin (Total)")]
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": ids})
    resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"})
    assert resp.status_code == 200
    sections = {s["key"]: s for s in json.loads(resp.json()["sections"])}
    assert list(sections) == ["overview", "executive", "findings", "abnormal", "terms", "questions", "limitations"]
    assert sections["overview"]["content"].splitlines() == [
        "Blood test / laboratory report dated 14 Sep 2026.",
        "5 confirmed result(s) covering Lipid profile, Liver function, Blood glucose.",
        "2 result(s) are flagged by the laboratory.",
    ]
    findings = sections["findings"]["content"]
    assert "HDL: 41.2 mg/dL — reference range printed on the report: Desirable > 40.0; Higher Risk < 40.0" in findings
    assert "Glucose (fasting): 126.30 mg/dL — reference range printed on the report: 70 - 100 — marked high" in findings
    flagged = sections["abnormal"]["content"]
    assert "HbA1c: 6.4 % — marked high by the laboratory" in flagged and "HDL" not in flagged.split("\n")[0]
    limits = sections["limitations"]["content"]
    assert "17 extracted value(s) have not been confirmed and are not included." in limits
    assert resp.json()["generator"] == "language-model"
    # the model only sees confirmed tests, printed flags as "marked … by the laboratory", no ranges/raw text
    prompt = provider.calls[0]["user"]
    assert "Triglycerides" not in prompt and "document_text" not in prompt and "Desirable" not in prompt
    assert prompt.count("marked high by the laboratory") == 2
    assert "Lipid profile" in prompt
    # summaries never change the review state
    assert client.get(f"/api/v1/reports/{rid}").json()["review_status"] == "partially_confirmed"


def test_summary_modes_differ_and_clinical_needs_no_language_model(client, monkeypatch):
    login(client, "modes@example.com")
    rid = upload(client, REALISTIC)
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    ids = [c["id"] for c in extraction(client, rid)["candidates"]]
    client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": ids})
    provider = Provider()
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: provider)

    def keys(mode):
        resp = client.post(f"/api/v1/reports/{rid}/summary", data={"mode": mode})
        assert resp.status_code == 200, resp.text
        return {s["key"]: s["content"] for s in json.loads(resp.json()["sections"])}, resp.json()

    quick, _ = keys("quick")
    standard, _ = keys("standard")
    detailed, _ = keys("detailed")
    assert list(quick) == ["executive", "findings", "abnormal"]
    assert "reference range" not in quick["findings"] and "Glucose (fasting): 126.30 mg/dL (marked high)" in quick["findings"]
    assert {"normal", "extraction"} <= set(detailed) and not {"normal", "extraction"} & set(standard)
    assert "(page 2)" in detailed["findings"] and "(page" not in standard["findings"]
    assert len("".join(detailed.values())) > len("".join(standard.values())) > len("".join(quick.values()))
    assert [c["max_tokens"] for c in provider.calls] == [450, 800, 1400]
    assert "one explanation for each listed test" in provider.calls[2]["system"]

    calls_before = len(provider.calls)
    monkeypatch.setattr(report_summary, "get_text_ai_provider",
                        lambda: (_ for _ in ()).throw(TextAIUnavailable("down")))
    clinical, body = keys("clinical")
    assert len(provider.calls) == calls_before and body["generator"] == "structured-data" and body["text_model"] is None
    assert list(clinical) == ["overview", "findings", "abnormal", "provenance", "limitations"]
    assert "HDL | 41.2 mg/dL | ref Desirable > 40.0; Higher Risk < 40.0 | no flag | 14 Sep 2026 | p.1" in clinical["findings"]
    assert "Source document: Lab_Report.pdf (original stored unchanged)." in clinical["provenance"]
    assert "AI-generated" in body["safety_message"]
    # AI modes still report unavailability cleanly
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "standard"}).status_code == 503


def test_trends_use_earlier_confirmed_results_only(client, monkeypatch):
    login(client, "trends@example.com")
    monkeypatch.setattr(report_summary, "get_text_ai_provider", lambda: Provider())
    older = upload(client, text_pdf(["Collected: 2025-09-01", "HDL Cholesterol 38.5 mg/dL 40 - 60 L",
                                     "HbA1c 6.9 % 4.0 - 5.6 H"]))
    client.post(f"/api/v1/reports/{older}/review/confirm", json={"report_date": "2025-09-01",
                "candidate_ids": [c["id"] for c in extraction(client, older)["candidates"]]})
    unconfirmed = upload(client, text_pdf(["Collected: 2026-01-01", "HDL Cholesterol 99 mg/dL 40 - 60"]))
    newer = upload(client, REALISTIC)
    client.post(f"/api/v1/reports/{newer}/date/confirm", json={"report_date": "2026-09-14"})
    by_name = cands(client, newer)
    client.post(f"/api/v1/reports/{newer}/review/confirm",
                json={"candidate_ids": [by_name["HDL"]["id"], by_name["HbA1c"]["id"], by_name["SGOT"]["id"]]})
    resp = client.post(f"/api/v1/reports/{newer}/summary", data={"mode": "standard"})
    trends = next(s["content"] for s in json.loads(resp.json()["sections"]) if s["key"] == "trends")
    assert trends.splitlines() == [
        "HDL: 41.2 mg/dL on 14 Sep 2026; previously 38.5 mg/dL on 1 Sep 2025 (change +2.7 mg/dL)",
        "HbA1c: 6.4 % on 14 Sep 2026; previously 6.9 % on 1 Sep 2025 (change -0.5 %)",
    ]
    assert "99" not in trends        # unconfirmed values never become history
    assert unconfirmed


def test_summary_safety_allows_repeating_laboratory_flags_only():
    ok = "The laboratory marked LDL high and flagged HbA1c. HDL (high-density lipoprotein) was measured."
    assert report_summary.safety_violations(ok, []) == []
    listed = "The laboratory marked HbA1c, Glucose (fasting), and LDL as high. Why is the laboratory marking LDL as high?"
    assert report_summary.safety_violations(listed, []) == []
    for bad in ("Your LDL is high.", "HbA1c, Glucose and LDL are high.", "LDL was marked. Values are high.", "HbA1c is elevated, which suggests diabetes.", "This confirms fatty liver.",
                "Consider a statin."):
        assert report_summary.safety_violations(bad, []), bad


def test_search_finds_confirmed_values_units_dates_and_types_only(client):
    login(client, "search7b@example.com")
    rid = upload(client, REALISTIC)
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    by_name = cands(client, rid)
    client.post(f"/api/v1/reports/{rid}/review/confirm",
                json={"candidate_ids": [by_name["Triglycerides"]["id"], by_name["SGOT"]["id"]]})
    meas = {m["id"]: m for m in client.get("/api/v1/measurements").json()}

    def search(q):
        body = client.post("/api/v1/search", json={"query": q}).json()
        return body["report_ids"], sorted(meas[i]["test_name"] for i in body["measurement_ids"])

    assert search("triglycerides") == ([rid], ["Triglycerides"])
    assert search("17.61") == ([rid], ["SGOT"])
    assert search("U/L") == ([rid], ["SGOT"])
    assert search("2026-09-14") == ([rid], ["SGOT", "Triglycerides"])
    assert search("14 Sep 2026")[0] == [rid]
    assert search("blood tests") == ([rid], [])
    assert search("Lab_Report") == ([rid], [])
    # unconfirmed extracted values are never searchable as clinical history
    assert search("VLDL") == ([], []) and search("41.2") == ([], [])


def test_search_ignores_provisional_report_dates(client):
    login(client, "search7b-date@example.com")
    rid = upload(client, REALISTIC)
    report = client.get(f"/api/v1/reports/{rid}").json()
    assert report["date_confirmed"] is False and report["detected_date"]

    def found(q):
        return client.post("/api/v1/search", json={"query": q}).json()["report_ids"]

    assert found(report["report_date"][:10]) == []          # extracted but not confirmed
    assert found("last 12 months") == []                     # time windows need a confirmed date too
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    assert found("2026-09-14") == [rid]


def test_new_review_endpoints_enforce_ownership(client):
    login(client, "owner7b@example.com")
    rid = upload(client, REALISTIC)
    cid = next(iter(cands(client, rid).values()))["id"]
    login(client, "intruder7b@example.com")
    assert client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-01-01"}).status_code == 404
    assert client.post(f"/api/v1/reports/{rid}/candidates/{cid}/confirm").status_code == 404
    own = upload(client, AMBIGUOUS)
    client.post(f"/api/v1/reports/{own}/date/confirm", json={"report_date": "2026-09-05"})
    assert client.post(f"/api/v1/reports/{own}/candidates/{cid}/confirm").status_code == 404
    assert client.post(f"/api/v1/reports/{own}/review/confirm", json={"candidate_ids": [cid]}).status_code == 409
    with Session(engine) as s:
        assert s.exec(select(MedicalMeasurement)).all() == []


def test_ingestion_and_review_never_call_the_text_ai(client, monkeypatch):
    login(client, "noai7b@example.com")

    def boom():
        raise AssertionError("text AI must not be used during ingestion or review")

    monkeypatch.setattr(report_summary, "get_text_ai_provider", boom)
    rid = upload(client, REALISTIC)
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    ids = [c["id"] for c in extraction(client, rid)["candidates"]]
    assert client.post(f"/api/v1/reports/{rid}/review/confirm", json={"candidate_ids": ids}).status_code == 200
    assert client.get(f"/api/v1/reports/{rid}").json()["review_status"] == "confirmed"
    # clinical summaries work without any language model
    assert client.post(f"/api/v1/reports/{rid}/summary", data={"mode": "clinical"}).status_code == 200


def test_retry_is_allowed_until_a_value_is_confirmed(client, monkeypatch):
    """A report that only had a summary (legacy status "completed") and no confirmed values can be reprocessed."""
    login(client, "retry7b@example.com")
    rid = upload(client, REALISTIC)
    with Session(engine) as s:
        report = s.get(Report, rid)
        report.status = "completed"
        s.add(report)
        s.commit()
    assert client.post(f"/api/v1/reports/{rid}/extraction/retry").status_code == 200
    assert client.get(f"/api/v1/reports/{rid}").json()["review_status"] == "needs_review"
    client.post(f"/api/v1/reports/{rid}/date/confirm", json={"report_date": "2026-09-14"})
    first = extraction(client, rid)["candidates"][0]["id"]
    client.post(f"/api/v1/reports/{rid}/candidates/{first}/confirm")
    resp = client.post(f"/api/v1/reports/{rid}/extraction/retry")
    assert resp.status_code == 409 and "already confirmed" in resp.json()["detail"]
