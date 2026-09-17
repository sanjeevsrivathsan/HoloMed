# Medical Report Ingestion

How HoloMed turns an uploaded medical report (mainly blood tests) into reviewed, structured data
used by the Reports workspace, Health Timeline, Health Search, Clinical View and Overview.

> AI-generated information — not a diagnosis. Consult a qualified healthcare professional.
> HoloMed is a research/hackathon demonstration. Extraction is not clinically validated.

## 1. Workflow

```
Upload (PDF / PNG / JPEG)
  → validate (content signature, size ≤ 50 MB, document type)
  → store original unchanged
  → extract text (PDF text layer; OCR for scanned pages and images)
  → parse laboratory values (deterministic, no AI)
  → human review (accept / edit / reject, confirm report date)
  → canonical measurements (MedicalMeasurement, linked to the report)
  → optional AI summary (text AI provider, safety-checked)
  → Timeline · Search · Clinical View · Overview
```

### Report status

| Status | Meaning |
|---|---|
| `uploaded` | Original stored; processing about to start |
| `processing` | Text extraction / parsing in progress (background task) |
| `extracted` | Text extracted, no laboratory values recognised; ready for review |
| `needs_review` | Values found; waiting for the user to accept/edit/reject them |
| `confirmed` | Review confirmed; accepted values are canonical measurements |
| `completed` | An AI summary has been generated from confirmed data |
| `failed` | Extraction failed (reason code shown); retry is available |
| `ready` | Legacy status of reports created before this pipeline; shown as Completed |

### Processing stages

Processing is a background task with explicit stages, recorded in `reportextraction.stage` and
returned as `stages` by `GET /api/v1/reports/{id}/extraction`:

| Stage | Mandatory | Notes |
|---|---|---|
| Upload | yes | Validation (signature, size, type) and storage of the unchanged original |
| Extract text | yes | PDF text layer |
| OCR fallback | only when needed | Runs only for pages/images without a text layer; otherwise `skipped` ("Not required") |
| Extract structured data | yes | Deterministic parser; 0 values is a valid result for non-lab documents |
| Save report | yes | Candidates, document date and status in one transaction |
| AI summary | **no** | Not part of processing. Generated later, on request, from confirmed data |

Each stage is `pending`, `active`, `completed`, `skipped`, `failed` or `not_reached`.

- On failure, the failing stage is `failed` and every later stage is `not_reached`; nothing after
  a failure is shown as completed.
- The failed stage carries a readable reason, for example: "The report text was extracted, but
  structured measurements could not be created. You can retry processing." Text extracted before
  the failure is kept and can be viewed.
- Error codes: `pdf_unreadable`, `pdf_encrypted`, `pdf_empty`, `image_unreadable`,
  `ocr_unavailable`, `no_text_found`, `file_missing`, `structured_extraction_failed`,
  `persistence_failed`, `internal_error`.

The upload dialog and report detail show these stages live, polling while processing. "Report
processed" appears only when every stage is `completed` or `skipped`. Text AI availability is
shown separately ("AI summary unavailable … report processing is not affected"). Upload,
extraction, review and confirmation never call the text AI provider.

## 2. Data model

No new report or measurement tables were added for blood tests. The pipeline reuses:

- `report`: document metadata, storage key and status (existing table).
- `medicalmeasurement`: canonical values (existing table). Rows are created **only** when the user
  confirms review. They get `report_id`, `report_date`, `source_location` ("Page N") and a comment
  ("Confirmed during review" or "Edited during review").
- `reportsummary`: the AI summary (existing table).
- `sourcereference`: one `document` reference per report (`report:<id>`; never a filesystem path).

Two derived-artifact tables were added (Alembic revisions `7a1c2e3d4f50` and `7a2b3c4d5e60`, which
adds `reportextraction.stage`):

- `reportextraction`: one row per report. Holds the extracted text, method (`pdf_text`, `ocr`,
  `pdf_text+ocr`), quality, page and character counts, the document date, an error code, warnings
  and timings.
- `extractedmeasurement`: value candidates awaiting review. Each row holds the canonical name,
  the name as printed, the value as printed, unit, printed range, printed flag, confidence, page,
  source line, review status and a link to the confirmed measurement.

The original upload is never modified. Deleting a report removes its derived rows. Removing demo
data also deletes the demo files.

**Schema upgrades:** the backend creates missing tables at startup but cannot add columns to
existing tables. If a model column is missing, startup logs `Database schema is out of date
(missing columns: …)`. Apply the migrations with
`python -m alembic -c backend/alembic/alembic.ini upgrade head`. A database whose Phase 7A tables
were created by startup rather than by Alembic must first be stamped with
`… stamp 7a1c2e3d4f50`, then upgraded.

## 3. Extraction

- **PDF:** `pypdf` reads the text layer. Pages with fewer than 40 characters are treated as scanned.
- **OCR (optional):** `rapidocr-onnxruntime` + `pypdfium2`
  (`pip install -r backend/requirements-ocr.txt`). OCR runs locally on the CPU and is used for
  scanned PDF pages and PNG/JPEG uploads.
  - Without the OCR packages, the upload dialog offers PDF only.
  - Pages without text are reported as unreadable ("OCR is not installed on this server").
- **Uncertainty:** OCR output is marked `quality: low`, adds a warning, and never gets
  high-confidence values.
- **Limits:** encrypted or damaged PDFs fail with a clear reason. Only the first 50 pages are processed.

## 4. Laboratory value parsing

`backend/services/lab_parser.py` is deterministic:

- **Canonical names** match the Health Timeline: HbA1c, LDL, HDL, Hemoglobin, WBC,
  Glucose (fasting), Creatinine, Blood Pressure (systolic/diastolic). `120/80 mmHg` is split into
  two values. Plain "Glucose" stays "Glucose"; fasting is never assumed.
- **Unrecognised tests** are offered only when the line also prints a reference range.
- **Reference ranges and flags** (H/L/High/Low/Abnormal/Normal/`*`) are taken only from the
  document. HoloMed never computes a flag from a range and never invents a range.
- **Confidence** is lowered for:
  - OCR output
  - values printed with `<`/`>`
  - missing units
  - values outside a loose plausibility window for the unit (this only lowers confidence; it
    never flags a result)
- **Dates:** a collection date is preferred over a report date. Ambiguous day/month dates
  (e.g. `03/04/2025`) are not guessed; the user enters the date during review.
- **OCR spacing:** OCR often drops spaces ("FastingBloodGlucose", "SerumCreatinine",
  "BloodPressure:124/80mmHg") or glues a date to its time ("02-Sep-202608:15"). Canonical names,
  blood pressure and dates are also matched in that compact form. Compact matching never creates
  new canonical names; for example "RandomGlucose" and "TotalCholesterol" stay unmapped.

## 5. Review

The Reports workspace shows each candidate with:

- "Auto-extracted" or "Edited by you"
- a confidence badge
- the source page and line
- the printed range and flag

The user can accept, reject, undo, edit (name, value, unit, printed range, printed flag) or
accept all remaining values, then confirm with the report date. Values not accepted are not
saved. Confirmed values cannot be edited through the review endpoint.

## 6. AI summary

`backend/services/explanation/report_summary.py` uses the configured text AI provider
(`TEXT_AI_PROVIDER`, default local Ollama).

- **Input:**
  - Lab reports: the model receives only the confirmed test names, values and units, never the
    document text.
  - Other documents with no confirmed values: the extracted text (first 6,000 characters).
  - With `TEXT_AI_PROVIDER=omniroute` this text leaves the machine.
- **Deterministic sections:** "Confirmed results", "Results flagged in the report" and "Results
  marked normal" are written by the backend from confirmed data. Only printed flags appear, and
  unflagged values are explicitly not judged.
- **Model sections:** the model writes only the overview, general explanations of the tests,
  and neutral questions for a clinician.
- **Validation:** output is rejected, with one retry and then HTTP 502, if it contains:
  - condition or diagnosis language
  - treatment, medication or lifestyle advice
  - value judgements (high/low/normal/elevated…)
  - claims about the person
  - numbers not present in the source
- **Safety notice:** the backend attaches "AI-generated information — not a diagnosis. Consult a
  qualified healthcare professional." to every summary, and the UI always shows it.
- **Provider unavailable:** HTTP 503 with a friendly message; nothing is saved.

## 7. Search, timeline, clinical view, overview

- **Health Search** (`POST /api/v1/search`) interprets queries deterministically and returns only
  existing record ids plus the interpretation it used. It understands:
  - test names and synonyms (e.g. "cholesterol" → LDL + HDL, "blood pressure")
  - time windows ("last two years", "past 6 months", "since 2024", "in 2025")
  - printed flags ("flagged", "abnormal", "high", "low"; "low-density" is not a flag)
  - document types

  Every measurement row links to its source report.
- **Health Timeline:** charts confirmed measurements per canonical test, draws only printed
  range limits, warns about mixed units, and links each record to its report.
- **Clinical View:** shows confirmed values with the previous confirmed value. The trend arrow
  shows direction only, with no good/bad colouring. It also shows the summary with its safety
  notice and the source-document artifacts.
- **Overview:** shows real counts (reports, imaging studies, AI report summaries), items that are
  processing, awaiting review or failed, recent reports, and confirmed HbA1c values.

## 8. Demo data

Settings → **Demo Data** → **Load Demo Data** (opt-in) creates three synthetic blood test PDFs.
They are dated about 690, 360 and 20 days ago and marked "SYNTHETIC DEMONSTRATION REPORT - NOT
REAL PATIENT DATA", with source "HoloMed demo (synthetic)".

- They go through the normal pipeline.
- The two older reports are confirmed automatically; the newest is left in review.
- **Remove Demo Data** deletes them and everything derived from them.

## 9. API

| Method & path | Purpose |
|---|---|
| `GET /api/v1/reports/capabilities` | Supported formats (depends on OCR), size limit, document types |
| `POST /api/v1/reports` | Upload (multipart: `file`, `type`, optional `title`, `laboratory`, `hospital`, `report_date`) |
| `GET /api/v1/reports` | List with status, extraction status, candidate/measurement counts, summary |
| `GET /api/v1/reports/{id}` · `/download` · `DELETE` | Metadata · original file · delete (with derived data) |
| `GET /api/v1/reports/{id}/extraction` | Processing `stage` and `stages`, extracted text, method, quality, warnings, timings, candidates |
| `POST /api/v1/reports/{id}/extraction/retry` | Re-run extraction (not after confirmation) |
| `PATCH /api/v1/reports/{id}/candidates/{cid}` | Edit / accept / reject / undo a candidate |
| `POST /api/v1/reports/{id}/review/confirm` | `{report_date}` → canonical measurements |
| `GET/POST /api/v1/reports/{id}/summary` | Read / generate (form field `mode`) |
| `POST /api/v1/search` | Structured search (`report_ids`, `measurement_ids`, `interpretation`) |
| `GET /api/v1/ai/status` | Text AI provider, model and state (no URLs or keys) |
| `GET /api/v1/demo` · `POST /api/v1/demo/load` · `DELETE /api/v1/demo` | Synthetic demo data |

All endpoints require the session cookie and only return the caller's own data.

## 10. Privacy and logging

- Logs contain report ids, methods, counts, error codes and timings only. They never contain
  document text, values, titles, file names or credentials; a test enforces this.
  `pypdf`'s own logger is limited to errors.
- Audit events include `report_uploaded`, `report_extraction_completed` / `_failed` / `_retried`,
  `report_review_confirmed`, `report_summary_generated`, `report_downloaded`, `report_deleted`
  and `demo_data_loaded` / `_removed`. They carry ids and counts only.
- The API does not expose storage keys or filesystem paths.
- HoloMed makes no regulatory or compliance claims.

## 11. Measured performance

Measured on the development machine (Windows 11, local backend, Ollama `qwen3:8b` on an RTX 3070 Ti).

| Step | Time |
|---|---|
| Text-layer PDF extraction + parsing (1 page, backend) | ~3 ms (first request after start: ~50 ms) |
| Upload → "ready for review" in the browser (1-page PDF, includes polling) | 0.2–2.4 s |
| OCR of a 1-page PNG (backend, CPU) | ~1.2–1.7 s |
| Upload → review ready for a scanned PNG (browser) | 2.1–2.6 s |
| AI summary, standard mode (local qwen3:8b, including validation) | 5–11 s when the model is on the GPU; roughly 1 in 3 answers needs a retry (+~5 s). Much slower when Ollama is busy or partly on the CPU (see Troubleshooting). |
| Realistic synthetic 2-page lab PDF (~1 MB, Chromium-generated, 11 values): upload → processed | 0.35–0.65 s (backend extraction 16–81 ms; OCR skipped) |
| Scanned 1-page synthetic lab PDF (OCR): upload → processed | 4.7–5.7 s (backend OCR ~3.9 s) |
| Structured search (browser round trip) | 70–260 ms |
| Load demo data (3 reports) | 0.1–0.35 s |

## 12. Limitations

- **Parser coverage:** the parser covers common single-line table layouts. Multi-column layouts,
  results that wrap across lines, and unusual units may be missed or need editing during review.
- **Units:** values are not converted between units; the timeline warns when units differ.
- **Canonical tests:** only the listed tests have canonical names. Other tests keep their printed
  names and are not charted.
- **OCR** quality depends on scan quality. Handwriting is not supported.
- **No cancel after upload:** in-flight uploads can be cancelled, but server-side processing
  cannot. It is short, and failed or interrupted runs can be retried; a run stuck in
  `processing` for more than 10 minutes can also be retried.
- **Background tasks** run in the API process. A restart during processing leaves the report in
  `processing` until retried.
- **Language model output** is filtered but can still be unhelpful. The filter is conservative and
  sometimes rejects acceptable text (hence the retry).
- **Upload rate:** upload endpoints have no rate limiting.

## 13. Troubleshooting

- **The upload dialog shows "Processing Pipeline … Processing failed. Please try again."**
  That dialog belongs to the pre-Phase-7A frontend. It posted the upload as JSON
  (`JSON.stringify(FormData)` is `"{}"`), which the API rejects with 422 `body.file: Field required`
  before anything is stored. Reload the page (Ctrl+Shift+R) so the browser loads the current
  frontend; a tab opened before the update can keep running the old bundle. The current dialog
  lists stages as Upload / Extract text / OCR fallback / Extract structured data / Save report.
- **"AI summary unavailable".** The report is still processed; only the summary is missing.
  - Ollama handles one request at a time. Another application sending it long prompts will make
    HoloMed's request wait and time out after `TEXT_AI_TIMEOUT_SECONDS` (default 90). Check
    `%LOCALAPPDATA%\Ollama\server.log`.
  - A very large context (for example 40,960 tokens) plus the preloaded vision model can push
    `qwen3:8b` partly onto the CPU (~2 tokens/s), or make model loading fail on an 8 GB GPU.
  - Retry when Ollama is idle.
