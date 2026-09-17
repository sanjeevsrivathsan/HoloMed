"""Deterministic parser for laboratory values in extracted report text.

Produces measurement *candidates* for human review. Rules:
- values, units, reference ranges and flags are taken only from the text;
  nothing is computed, inferred or filled in;
- recognised analytes get a canonical name (the names the Health Timeline uses);
- anything uncertain gets a lower confidence instead of a guess.
No LLM is involved.
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Tuple

# Canonical names are shared with the frontend Health Timeline.
HBA1C = "HbA1c"
LDL = "LDL"
HDL = "HDL"
HEMOGLOBIN = "Hemoglobin"
WBC = "WBC"
GLUCOSE_FASTING = "Glucose (fasting)"
GLUCOSE = "Glucose"
CREATININE = "Creatinine"
BP_SYS = "Blood Pressure (systolic)"
BP_DIA = "Blood Pressure (diastolic)"

# Order matters: more specific patterns first (HbA1c before Hemoglobin).
ANALYTES: List[Tuple[str, str]] = [
    (HBA1C, r"(?:hb\s?a1c|a1c|glyc(?:osyl)?ated\s+ha?emoglobin(?:\s+a1c)?|ha?emoglobin\s+a1c)"),
    (LDL, r"(?:ldl(?:[\s-]?c)?(?:\s+cholesterol)?|low[\s-]density\s+lipoprotein(?:\s+cholesterol)?)"),
    (HDL, r"(?:hdl(?:[\s-]?c)?(?:\s+cholesterol)?|high[\s-]density\s+lipoprotein(?:\s+cholesterol)?)"),
    (HEMOGLOBIN, r"(?:ha?emoglobin|hgb|hb)"),
    (WBC, r"(?:wbc(?:\s+count)?|white\s+blood\s+cells?(?:\s+count)?|total\s+leu[ck]ocyte\s+count|tlc|leu[ck]ocytes?)"),
    (GLUCOSE_FASTING, r"(?:fasting\s+(?:blood\s+|plasma\s+|serum\s+)?(?:glucose|sugar)|(?:plasma\s+|blood\s+)?glucose\s+fasting|fbs|fpg)"),
    (GLUCOSE, r"(?:(?:blood\s+|plasma\s+|serum\s+)?glucose)"),
    (CREATININE, r"(?:creatinine)"),
]
_ANALYTE_RES = [(name, re.compile(pat + r"$", re.I)) for name, pat in ANALYTES]

# Units a canonical analyte is usually reported in, with loose plausibility bounds
# (used only to lower confidence on likely OCR/parse errors, never to flag results).
PLAUSIBLE = {
    HBA1C: {"%": (2, 20), "mmol/mol": (5, 200)},
    LDL: {"mg/dl": (5, 600), "mmol/l": (0.1, 16)},
    HDL: {"mg/dl": (5, 200), "mmol/l": (0.1, 6)},
    HEMOGLOBIN: {"g/dl": (2, 25), "g/l": (20, 250), "mmol/l": (1, 16)},
    WBC: {"x10^3/ul": (0.1, 200), "10^3/ul": (0.1, 200), "k/ul": (0.1, 200), "x10^9/l": (0.1, 200),
          "10^9/l": (0.1, 200), "/ul": (100, 200000), "cells/ul": (100, 200000), "/cumm": (100, 200000),
          "cells/cumm": (100, 200000)},
    GLUCOSE_FASTING: {"mg/dl": (10, 1500), "mmol/l": (0.5, 80)},
    GLUCOSE: {"mg/dl": (10, 1500), "mmol/l": (0.5, 80)},
    CREATININE: {"mg/dl": (0.05, 30), "umol/l": (5, 2500), "µmol/l": (5, 2500), "μmol/l": (5, 2500)},
    BP_SYS: {"mmhg": (50, 300)},
    BP_DIA: {"mmhg": (20, 200)},
}

_UNIT = (r"(?:%|mmol/mol|mg/dl|mg/l|g/dl|g/l|mmol/l|[uµμ]mol/l|mmhg|mm\s?hg|iu/l|u/l|miu/l|[uµμ]iu/ml|"
         r"meq/l|ng/ml|pg/ml|ng/dl|fl|pg|"
         r"(?:x\s?)?10\^?\s?[39]\s?/\s?[uµμ]?l|x10\^?[39]/[uµμ]?l|k/[uµμ]l|thou/[uµμ]l|"
         r"cells/[uµμ]l|cells/cumm|/cumm|/[uµμ]l|mill/cumm|million/[uµμ]l)")
_NUM = r"\d+(?:[.,]\d+)?"
_RANGE = (rf"(?:{_NUM}\s*(?:-|–|—|to)\s*{_NUM}|[<>≤≥]=?\s*{_NUM}|(?:up\s*to|upto)\s*{_NUM})")
_FLAG_TOKEN = r"(?:H|L|HH|LL|HIGH|LOW|High|Low|ABNORMAL|Abnormal|NORMAL|Normal|\*)"

_LINE_RE = re.compile(
    rf"^(?P<name>[A-Za-z][A-Za-z0-9 ,()\-/.'&]*?[A-Za-z)])\s*[:\-–]?\s+"
    rf"(?P<value>[<>]?\s?{_NUM})\s*"
    rf"(?:(?P<flag1>{_FLAG_TOKEN})\s+)?"
    rf"(?P<unit>{_UNIT})?\s*"
    rf"(?:[\[(]?\s*(?:ref(?:erence)?\.?\s*(?:range|interval)?\s*[:\-]?\s*)?(?P<range>{_RANGE})\s*(?P<runit>{_UNIT})?\s*[\])]?)?\s*"
    rf"(?P<flag2>{_FLAG_TOKEN})?\s*$",
    re.I,
)
_BP_RE = re.compile(r"\b(?:blood\s+pressure|b\.?p\.?)\b\s*[:\-]?\s*(\d{2,3})\s*/\s*(\d{2,3})\s*(mm\s?hg)?", re.I)
_PAGE_RE = re.compile(r"^--- Page (\d+) ---$")

_STOP_NAMES = re.compile(
    r"^(?:page|date|age|sex|gender|phone|tel|mobile|fax|patient|pt|id|uhid|mrn|ref(?:erred)?|sample|"
    r"specimen|collected|received|reported|lab|visit|bed|room|registration|reg|order|accession|dob|"
    r"barcode|pin|zip|time|year)\b",
    re.I,
)

_FLAG_MAP = {"h": "high", "hh": "high", "high": "high", "l": "low", "ll": "low", "low": "low",
             "abnormal": "abnormal", "*": "abnormal", "normal": "normal"}


@dataclass
class Candidate:
    test_name: str
    source_name: str
    value: Optional[float]
    value_text: str
    unit: str = ""
    reference_range: Optional[str] = None
    flag: str = "unknown"
    confidence: str = "medium"
    page: Optional[int] = None
    line_text: str = ""


@dataclass
class ParseResult:
    candidates: List[Candidate] = field(default_factory=list)
    document_date: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def _clean_name(name: str) -> str:
    name = re.sub(r"\([^)]*\)", " ", name)          # drop "(HPLC)" etc.
    name = re.sub(r"^(?:serum|s\.|plasma)\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"[,.:\-]+$", "", name.strip())
    return re.sub(r"\s+", " ", name).strip()


def canonical_name(source_name: str) -> Optional[str]:
    cleaned = _clean_name(source_name)
    for name, rx in _ANALYTE_RES:
        if rx.match(cleaned):
            return name
    return None


def _norm_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit or "").lower()


def _to_float(text: str) -> Optional[float]:
    try:
        return float(text.replace(",", ".").lstrip("<>").strip())
    except ValueError:
        return None


def _lower(conf: str) -> str:
    return {"high": "medium", "medium": "low"}.get(conf, "low")


def _plausible(test_name: str, unit: str, value: Optional[float]) -> Optional[bool]:
    table = PLAUSIBLE.get(test_name)
    if table is None or value is None:
        return None
    bounds = table.get(_norm_unit(unit))
    if bounds is None:
        return None
    return bounds[0] <= value <= bounds[1]


def _parse_line(line: str, page: Optional[int]) -> List[Candidate]:
    bp = _BP_RE.search(line)
    if bp:
        unit = "mmHg"
        out = []
        for name, raw in ((BP_SYS, bp.group(1)), (BP_DIA, bp.group(2))):
            value = float(raw)
            conf = "high" if bp.group(3) else "medium"
            if _plausible(name, unit, value) is False:
                conf = "low"
            out.append(Candidate(test_name=name, source_name=line[: bp.start(1)].strip(" :-") or "Blood Pressure",
                                 value=value, value_text=raw, unit=unit,
                                 confidence=conf, page=page, line_text=line))
        return out

    m = _LINE_RE.match(line)
    if not m:
        return []
    source_name = m.group("name").strip()
    if len(_clean_name(source_name)) < 2 or _STOP_NAMES.match(source_name):
        return []
    canonical = canonical_name(source_name)
    rng = m.group("range")
    unit = (m.group("unit") or m.group("runit") or "").strip()
    if canonical is None and not rng:
        return []   # unrecognised line without a printed range: too noisy to offer
    value_text = m.group("value").replace(" ", "")
    value = _to_float(value_text)
    flag_raw = (m.group("flag1") or m.group("flag2") or "").lower()
    flag = _FLAG_MAP.get(flag_raw, "unknown")

    if canonical:
        conf = "high" if unit and value is not None else "medium"
        plausible = _plausible(canonical, unit, value)
        if plausible is False:
            conf = "low"
        elif plausible is None and unit:
            conf = "medium"
    else:
        conf = "medium" if unit else "low"
    if value_text[:1] in "<>":
        conf = _lower(conf)
    return [Candidate(test_name=canonical or _clean_name(source_name), source_name=source_name, value=value,
                      value_text=value_text, unit=unit, reference_range=(rng.strip() if rng else None),
                      flag=flag, confidence=conf, page=page, line_text=line)]


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DATE_LABEL = re.compile(
    r"(?P<label>collect(?:ed|ion)(?:\s+(?:date|on))?|sample\s+(?:date|drawn|collected)|"
    r"report(?:ed)?\s*(?:date|on)|date\s+of\s+(?:report|collection)|test\s+date|date)\s*[:\-]?\s*(?P<rest>.+)",
    re.I,
)
_ISO = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
_DMY_TEXT = re.compile(r"\b(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})\b")
_MDY_TEXT = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b")


def _mk(y: int, mo: int, d: int) -> Optional[date]:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_date(text: str) -> Tuple[Optional[date], bool]:
    """Return (date, ambiguous). Day/month order is never guessed."""
    if m := _ISO.search(text):
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3))), False
    if m := _DMY_TEXT.search(text):
        mo = _MONTHS.get(m.group(2)[:3].lower())
        if mo:
            return _mk(int(m.group(3)), mo, int(m.group(1))), False
    if m := _MDY_TEXT.search(text):
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            return _mk(int(m.group(3)), mo, int(m.group(2))), False
    if m := _NUMERIC.search(text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 >= b:
            return _mk(y, b, a), False
        if b > 12 >= a:
            return _mk(y, a, b), False
        if a == b:
            return _mk(y, a, b), False
        return None, True
    return None, False


def _label_rank(label: str) -> int:
    label = label.lower()
    if label.startswith("collect") or label.startswith("sample") or "collection" in label:
        return 0
    if label.startswith("report") or "report" in label or label.startswith("test"):
        return 1
    return 2


def find_document_date(lines: List[str]) -> Tuple[Optional[str], List[str]]:
    best: Optional[Tuple[int, date]] = None
    ambiguous = False
    for line in lines:
        m = _DATE_LABEL.search(line)
        if not m or re.search(r"\b(?:birth|dob)\b", line, re.I):
            continue
        found, amb = parse_date(m.group("rest"))
        ambiguous = ambiguous or amb
        if found and (best is None or _label_rank(m.group("label")) < best[0]):
            best = (_label_rank(m.group("label")), found)
    warnings = []
    if best is None and ambiguous:
        warnings.append("The report date could not be read unambiguously; please enter it during review.")
    elif best is None:
        warnings.append("No report date was found; please enter it during review.")
    return (best[1].isoformat() if best else None), warnings


def parse_report_text(text: str, ocr: bool = False) -> ParseResult:
    page: Optional[int] = None
    lines: List[str] = []
    result = ParseResult()
    seen = set()
    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        if pm := _PAGE_RE.match(line):
            page = int(pm.group(1))
            continue
        lines.append(line)
        for cand in _parse_line(line, page):
            key = (cand.test_name.lower(), cand.value_text, cand.unit.lower())
            if key in seen:
                continue
            seen.add(key)
            if ocr:
                cand.confidence = _lower(cand.confidence)
            result.candidates.append(cand)
    result.document_date, result.warnings = find_document_date(lines)
    if not result.candidates:
        result.warnings.append("No laboratory values were recognised; the document text is still available.")
    return result
