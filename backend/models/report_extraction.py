"""Derived artifacts of a report upload (never the original document).

ReportExtraction      one row per report: extracted text + how/when it was produced.
ExtractedMeasurement  measurement candidates parsed from that text, awaiting human
                      review. Only candidates the user confirms become canonical
                      MedicalMeasurement rows (linked back via measurement_id).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel


class ReportExtraction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id", index=True, unique=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    # pending | processing | succeeded | failed
    status: str = Field(default="pending")
    # last stage entered: text_extraction | ocr | structured_extraction | save | done
    # (on failure: the stage that failed)
    stage: Optional[str] = None
    # pdf_text | ocr | pdf_text+ocr | none
    method: str = Field(default="none")
    # good | low | unknown  (low = OCR or sparse text; review carefully)
    quality: str = Field(default="unknown")
    page_count: int = 0
    char_count: int = 0
    text: str = ""                       # derived, normalized text (never overwrites the original)
    document_date: Optional[str] = None  # collection/report date found in the document (ISO)
    error_code: Optional[str] = None     # short machine code, no document content
    warnings: str = "[]"                 # JSON list of short strings
    timings: str = "{}"                  # JSON {phase: ms}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractedMeasurement(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id", index=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    test_name: str                       # canonical name when recognised (e.g. "HbA1c")
    source_name: str                     # name as written in the document
    value: Optional[float] = None
    value_text: str                      # value exactly as written
    unit: str = ""
    reference_range: Optional[str] = None  # only when printed in the source
    flag: str = "unknown"                # only when printed in the source (H/L/…)
    confidence: str = "medium"           # high | medium | low
    page: Optional[int] = None
    line_text: str = ""                  # source line, for review
    # pending | accepted | rejected | confirmed
    review_status: str = Field(default="pending")
    edited: bool = False
    measurement_id: Optional[int] = Field(default=None, foreign_key="medicalmeasurement.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExtractedMeasurementRead(SQLModel):
    id: int
    test_name: str
    source_name: str
    value: Optional[float] = None
    value_text: str
    unit: str
    reference_range: Optional[str] = None
    flag: str
    confidence: str
    page: Optional[int] = None
    line_text: str
    review_status: str
    edited: bool
    measurement_id: Optional[int] = None


class ProcessingStage(SQLModel):
    key: str
    label: str
    state: str          # pending | active | completed | skipped | failed | not_reached
    detail: Optional[str] = None


class ReportExtractionRead(SQLModel):
    report_id: int
    status: str
    stage: Optional[str] = None
    stages: List[ProcessingStage] = []
    method: str
    quality: str
    page_count: int
    char_count: int
    text: str
    document_date: Optional[str] = None
    error_code: Optional[str] = None
    warnings: List[str] = []
    timings: dict = {}
    candidates: List[ExtractedMeasurementRead] = []
