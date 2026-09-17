"""Health Search over the user's own canonical data.

Queries are interpreted deterministically (test names, time windows, printed
flags, document types). Results are only ever existing report and
measurement ids owned by the caller; nothing is generated.
"""
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ..database import get_session
from ..dependencies.auth import get_current_user
from ..models import MedicalMeasurement, Report, SourceReference, User
from ..services import lab_parser
from ..services.report_pipeline import date_is_confirmed

router = APIRouter(prefix="/api/v1/search", tags=["Search"])


@router.get("/source-references")
def get_source_references(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    return session.exec(select(SourceReference).where(SourceReference.owner_id == user.id)).all()


class SearchRequest(BaseModel):
    query: str = Field(..., max_length=300)


class SearchInterpretation(BaseModel):
    tests: List[str] = []
    since: Optional[date] = None
    until: Optional[date] = None
    flags: List[str] = []
    report_types: List[str] = []


class SearchResponse(BaseModel):
    report_ids: List[int]
    measurement_ids: List[int]
    interpretation: SearchInterpretation = SearchInterpretation()


_TEST_TERMS = [(name, re.compile(r"\b" + pat + r"\b", re.I)) for name, pat in lab_parser.ANALYTES] + [
    (lab_parser.LDL, re.compile(r"\bcholesterol\b|\blipids?\b", re.I)),
    (lab_parser.HDL, re.compile(r"\bcholesterol\b|\blipids?\b", re.I)),
    (lab_parser.GLUCOSE, re.compile(r"\b(blood\s+)?sugar\b", re.I)),
    (lab_parser.GLUCOSE_FASTING, re.compile(r"\b(blood\s+)?sugar\b|\bglucose\b", re.I)),
    (lab_parser.BP_SYS, re.compile(r"\bblood\s+pressure\b|\bbp\b|\bsystolic\b", re.I)),
    (lab_parser.BP_DIA, re.compile(r"\bblood\s+pressure\b|\bbp\b|\bdiastolic\b", re.I)),
    (lab_parser.WBC, re.compile(r"\bwhite\s+(blood\s+)?cells?\b", re.I)),
]
_TYPE_TERMS = [
    ("Blood Test", re.compile(r"\bblood\s*(test|work|report)s?\b|\blab(oratory)?\b", re.I)),
    ("Imaging Report", re.compile(r"\bimaging\b|\bradiology\b|\bx-?rays?\b|\bscans?\b", re.I)),
    ("Discharge Summary", re.compile(r"\bdischarge\b", re.I)),
    ("Prescription", re.compile(r"\bprescriptions?\b", re.I)),
    ("Clinical Note", re.compile(r"\bclinical\s+notes?\b|\bnotes?\b", re.I)),
]
_DENSITY = re.compile(r"\b(high|low)[\s-]density\b", re.I)
_UNITS = {"day": 1, "week": 7, "month": 30.44, "year": 365.25}
_WINDOW = re.compile(r"\b(?:last|past|previous)\s+(\d+|one|two|three|four|five|six|twelve)?\s*"
                     r"(day|week|month|year)s?\b", re.I)
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "twelve": 12}
_SINCE = re.compile(r"\b(?:since|after|from)\s+((?:19|20)\d{2})\b", re.I)
_IN_YEAR = re.compile(r"\bin\s+((?:19|20)\d{2})\b", re.I)


def interpret(query: str, today: Optional[date] = None) -> SearchInterpretation:
    today = today or date.today()
    result = SearchInterpretation()
    for name, rx in _TEST_TERMS:
        if rx.search(query) and name not in result.tests:
            result.tests.append(name)
    if lab_parser.HBA1C in result.tests and lab_parser.HEMOGLOBIN in result.tests \
            and not re.search(r"\bha?emoglobin\b(?!\s+a1c)|\bhgb\b", query, re.I):
        result.tests.remove(lab_parser.HEMOGLOBIN)   # "HbA1c" should not also mean haemoglobin
    if m := _WINDOW.search(query):
        count = m.group(1)
        n = int(count) if count and count.isdigit() else _WORDS.get((count or "one").lower(), 1)
        result.since = today - timedelta(days=round(n * _UNITS[m.group(2).lower()]))
    elif m := _SINCE.search(query):
        result.since = date(int(m.group(1)), 1, 1)
    elif m := _IN_YEAR.search(query):
        result.since = date(int(m.group(1)), 1, 1)
        result.until = date(int(m.group(1)), 12, 31)
    flag_text = _DENSITY.sub(" ", query)
    if re.search(r"\b(abnormal|flagged|out\s+of\s+range)\b", flag_text, re.I):
        result.flags = ["high", "low", "abnormal"]
    else:
        if re.search(r"\b(high|elevated|raised)\b", flag_text, re.I):
            result.flags.append("high")
        if re.search(r"\blow\b", flag_text, re.I):
            result.flags.append("low")
    for name, rx in _TYPE_TERMS:
        if rx.search(query):
            result.report_types.append(name)
    return result


def _report_day(report: Report) -> Optional[date]:
    """The report date, only once the user has confirmed it (provisional dates are not searchable)."""
    if not date_is_confirmed(report):
        return None
    try:
        return datetime.fromisoformat(report.report_date[:10]).date()
    except (TypeError, ValueError):
        return None


def _in_window(day: Optional[date], spec: SearchInterpretation) -> bool:
    if spec.since is None and spec.until is None:
        return True
    if day is None:
        return False
    return (spec.since is None or day >= spec.since) and (spec.until is None or day <= spec.until)


def _keyword_matcher(query: str):
    """Plain query: a number matches confirmed values, a date matches report dates, text matches
    test names, units and laboratories."""
    lowered = query.lower()
    number = None
    if re.fullmatch(r"\d+(?:[.,]\d+)?", query):
        number = float(query.replace(",", "."))
    day, _ambiguous = lab_parser.parse_date(query) if re.search(r"\d{4}", query) else (None, False)

    def measurement(m: MedicalMeasurement) -> bool:
        if number is not None:
            return abs(m.value - number) < 1e-9
        if day is not None:
            return m.report_date == day
        return bool(lowered) and lowered in f"{m.test_name} {m.unit} {m.hospital or ''} {m.laboratory or ''}".lower()

    def report(r: Report) -> bool:
        if day is not None:
            return _report_day(r) == day
        text = f"{r.title} {r.type} {r.hospital or ''} {r.laboratory or ''} {r.department or ''}".lower()
        return bool(lowered) and number is None and lowered in text

    return measurement, report


@router.post("", response_model=SearchResponse)
def perform_search(
    request: SearchRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    query = request.query.strip()
    spec = interpret(query)
    structured = bool(spec.tests or spec.flags or spec.since or spec.report_types)
    keyword_measurement, keyword_report = _keyword_matcher(query)

    measurements = session.exec(select(MedicalMeasurement).where(MedicalMeasurement.owner_id == user.id)
                                .order_by(MedicalMeasurement.report_date)).all()
    matched_measurements = []
    for m in measurements:
        if structured:
            if spec.tests and m.test_name not in spec.tests:
                continue
            if spec.flags and m.flag not in spec.flags:
                continue
            if not _in_window(m.report_date, spec):
                continue
            if not (spec.tests or spec.flags):
                continue   # a time window or document type alone selects reports, not every value
        elif not keyword_measurement(m):
            continue
        matched_measurements.append(m)

    reports = session.exec(select(Report).where(Report.owner_id == user.id)).all()
    with_matches = {m.report_id for m in matched_measurements if m.report_id is not None}
    matched_reports = []
    for r in reports:
        text = f"{r.title} {r.type} {r.hospital or ''} {r.laboratory or ''} {r.department or ''}".lower()
        if structured:
            by_type = not spec.report_types or r.type in spec.report_types
            title_hit = any(rx.search(r.title) for name, rx in _TEST_TERMS if name in spec.tests)
            if spec.tests or spec.flags:
                hit = r.id in with_matches or (title_hit and not spec.flags)
            else:
                hit = True
            if hit and by_type and _in_window(_report_day(r), spec):
                matched_reports.append(r.id)
        elif keyword_report(r) or r.id in with_matches:
            matched_reports.append(r.id)

    return SearchResponse(report_ids=matched_reports, measurement_ids=[m.id for m in matched_measurements],
                          interpretation=spec)
