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


def _compact(pat: str) -> str:
    """Same pattern without whitespace, for OCR output that drops spaces ("FastingBloodGlucose")."""
    return re.sub(r"\\s[+?*]", "", pat).replace(r"[\s-]?", "-?").replace(r"[\s-]", "-?")


_ANALYTE_RES_COMPACT = [(name, re.compile(r"(?:serum|plasma)?" + _compact(pat) + r"$", re.I))
                        for name, pat in ANALYTES]

# Units a canonical analyte is usually reported in, with loose plausibility bounds
# (used only to lower confidence on likely OCR/parse errors, never to flag results).
PLAUSIBLE = {
    HBA1C: {"%": (2, 20), "mmol/mol": (5, 200)},
    LDL: {"mg/dl": (5, 600), "mmol/l": (0.1, 16)},
    HDL: {"mg/dl": (5, 200), "mmol/l": (0.1, 6)},
    HEMOGLOBIN: {"g/dl": (2, 25), "gm/dl": (2, 25), "gms/dl": (2, 25), "g/l": (20, 250), "mmol/l": (1, 16)},
    WBC: {"x10^3/ul": (0.1, 200), "10^3/ul": (0.1, 200), "k/ul": (0.1, 200), "x10^9/l": (0.1, 200),
          "10^9/l": (0.1, 200), "/ul": (100, 200000), "cells/ul": (100, 200000), "/cumm": (100, 200000),
          "cells/cumm": (100, 200000)},
    GLUCOSE_FASTING: {"mg/dl": (10, 1500), "mmol/l": (0.5, 80)},
    GLUCOSE: {"mg/dl": (10, 1500), "mmol/l": (0.5, 80)},
    CREATININE: {"mg/dl": (0.05, 30), "umol/l": (5, 2500), "µmol/l": (5, 2500), "μmol/l": (5, 2500)},
    BP_SYS: {"mmhg": (50, 300)},
    BP_DIA: {"mmhg": (20, 200)},
}

_UNIT = (r"(?:%|mmol/mol|mg/dl|mg/l|gm/dl|gms/dl|g/dl|g/l|mmol/l|[uµμ]mol/l|[uµμ]g/dl|[uµμ]g/l|mmhg|mm\s?hg|"
         r"iu/ml|iu/l|u/l|miu/l|m?[uµμ]iu/ml|meq/l|ng/ml|pg/ml|ng/dl|mm/hr|mm/1st\s?hr|fl|pg|"
         r"(?:x\s?)?10\^?\s?[369]\s?/\s?[uµμ]?l|x10\^?[369]/[uµμ]?l|k/[uµμ]l|thou/[uµμ]l|lakhs?/cumm|"
         r"cells/[uµμ]l|cells/cumm|/cumm|/[uµμ]l|mill/cumm|millions?/cumm|million/[uµμ]l)")
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
_BP_RE = re.compile(r"\b(?:blood\s*pressure|b\.?p\.?)\b\s*[:\-]?\s*(\d{2,3})\s*/\s*(\d{2,3})\s*(mm\s?hg)?", re.I)
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
    document_date: Optional[str] = None          # suggestion only; the user confirms the report date
    date_candidates: list = field(default_factory=list)   # List[DateCandidate]
    warnings: List[str] = field(default_factory=list)


def _clean_name(name: str) -> str:
    name = re.sub(r"\([^)]*\)", " ", name)          # drop "(HPLC)" etc.
    name = re.sub(r"^(?:serum|s\.|plasma)\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"[,.:\-]+$", "", name.strip())
    return re.sub(r"\s+", " ", name).strip()


def display_name(source_name: str) -> str:
    """Printed test name, whitespace-normalised (qualifiers in parentheses are kept)."""
    name = re.sub(r"\s+", " ", source_name).strip()
    name = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", name))
    return re.sub(r"[,.:\-]+$", "", name).strip()


def _match_analyte(cleaned: str) -> Optional[str]:
    for name, rx in _ANALYTE_RES:
        if rx.match(cleaned):
            return name
    compact = re.sub(r"\s+", "", cleaned)
    for name, rx in _ANALYTE_RES_COMPACT:
        if rx.match(compact):
            return name
    return None


_OTHER_SPECIMEN = re.compile(r"urine|urinary|csf|fluid|dialysate|24\s*-?\s*h", re.I)
_NOT_FASTING = re.compile(r"random|post|\bpp\b|prandial|\bhrs?\b|\d", re.I)


def canonical_name(source_name: str) -> Optional[str]:
    """Canonical timeline name, or None. Qualifiers in parentheses can only narrow or block a match:
    "(Fasting)" → fasting glucose; "(PP)", "(Random)", "(2 Hr)" or a non-blood specimen → unmapped."""
    name = _match_analyte(_clean_name(source_name))
    qualifiers = " ".join(re.findall(r"\(([^)]*)\)", source_name))
    if name is None or not qualifiers.strip():
        return name
    if _OTHER_SPECIMEN.search(qualifiers):
        return None
    conflicting = {a for q in re.findall(r"\(([^)]*)\)", source_name) for a in [_match_analyte(q.strip())] if a}
    if conflicting - {name}:
        return None     # e.g. "Haemoglobin (HbA1c)": name and qualifier disagree — do not guess
    if name in (GLUCOSE, GLUCOSE_FASTING):
        if _NOT_FASTING.search(qualifiers):
            return None
        if re.search(r"fasting|\bf\b", qualifiers, re.I):
            return GLUCOSE_FASTING
    return name


def _norm_unit(unit: str) -> str:
    return re.sub(r"\s+", "", unit or "").lower()


def _to_float(text: str) -> Optional[float]:
    text = text.lstrip("<>").strip()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):      # thousands separators: "7,900"
        text = text.replace(",", "")
    try:
        return float(text.replace(",", "."))
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
    """Single-line rows: "<name> <value> [flag] [unit] [range] [flag]" and blood pressure."""
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
    rng = m.group("range")
    unit = (m.group("unit") or m.group("runit") or "").strip()
    flag_raw = (m.group("flag1") or m.group("flag2") or "").lower()
    return _candidate(source_name, m.group("value"), unit, rng.strip() if rng else None,
                      _FLAG_MAP.get(flag_raw, "unknown"), page, line, require_range_if_unmapped=True)


def _candidate(source_name: str, value_text: str, unit: str, rng: Optional[str], flag: str,
               page: Optional[int], line_text: str, require_range_if_unmapped: bool) -> List[Candidate]:
    canonical = canonical_name(source_name)
    if canonical is None and (not rng if require_range_if_unmapped else not (rng or unit)):
        return []   # unrecognised test without a printed range/unit: too noisy to offer
    value_text = value_text.replace(" ", "")
    value = _to_float(value_text)
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
    return [Candidate(test_name=canonical or display_name(source_name), source_name=source_name, value=value,
                      value_text=value_text, unit=unit, reference_range=rng, flag=flag, confidence=conf,
                      page=page, line_text=line_text[:300])]


# ── Multi-line result blocks ────────────────────────────────────────────────────
# Many laboratory systems print each result as a block:
#     Total Cholesterol
#     Method: CHOD-PAP
#     182.40 mg/dL 125 - 200
# optionally followed by printed reference tiers on further lines.

_VALUE_LINE_RE = re.compile(
    rf"^(?P<value>[<>]?\s?{_NUM})\s*(?:(?P<flag1>H|L|HH|LL|\*)(?=\s|$)\s*)?(?P<unit>{_UNIT}(?=\s|$))?\s*(?P<rest>.*)$",
    re.I,
)
_META_LINE_RE = re.compile(
    r"^(?:method|sample|specimen|container|instrument|technique|principle|type)\s*[:\-]", re.I)
_TIER_WORDS = (r"(?:desirable|borderline|optimal|near\s*optimal|high|higher|low|lower|very|risk|normal|"
               r"deficien\w*|insufficien\w*|sufficien\w*|adults?|children|men|women|male|female|fasting|"
               r"non[\s-]?fasting|pre[\s-]?diabet\w*|diabet\w*|toxic|elevated|moderate|above|below|up\s*to)")
_TIER_START_RE = re.compile(rf"^[,;(\-]?\s*{_TIER_WORDS}\b", re.I)
_BLOCK_STOP_RE = re.compile(
    r"^(?:note|notes|comment|comments|remark|remarks|interpretation|impression|advice|disclaimer|"
    r"\*+\s*end|end\s+of\s+report|test\s+results?\b|test\s+name\b|investigation\b|page\b)", re.I)
_TRAILING_FLAG_RE = re.compile(r"^(?P<range>.*?\d)\s+(?P<flag>H|L|HH|LL|HIGH|LOW|ABNORMAL)$", re.I)
_SIMPLE_RANGE_RE = re.compile(rf"^(?:{_RANGE})(?:\s*{_UNIT})?$", re.I)
MAX_RANGE_CHARS = 200


def _is_name_line(line: str) -> bool:
    if len(line) > 60 or len(re.sub(r"[^A-Za-z]", "", line)) < 2:
        return False
    if not re.match(r"^[A-Za-z]", line) or line[0].islower():
        return False
    if ":" in line or re.search(r"[<>=≤≥]", line):
        return False
    if line.count("(") != line.count(")"):
        return False
    if re.search(_RANGE, line) and not re.search(r"\([^)]*\d[^)]*\)", line):
        return False
    if line.rstrip().endswith("."):
        return False
    if _STOP_NAMES.match(line) or _BLOCK_STOP_RE.match(line) or _TIER_START_RE.match(line):
        return False
    return True


def _is_range_continuation(line: str) -> bool:
    """Printed reference tiers that continue a result's range on following lines."""
    if len(line) > 60 or _META_LINE_RE.match(line) or _BLOCK_STOP_RE.match(line):
        return False
    if _TIER_START_RE.match(line) and (re.search(r"\d", line) or line.rstrip().endswith(")")):
        return True
    if re.match(rf"^[<>≤≥.]*\s*{_NUM}\s*(?:-|–|to)?\s*(?:{_NUM})?\s*(?:{_UNIT})?\s*\(?[A-Za-z ]*\)?$", line, re.I) \
            and re.search(r"\(|[<>]|-", line):
        return True
    return bool(re.fullmatch(r"[A-Za-z ]{1,20}\)", line))       # "High)" — wrapped tier label


def _parse_blocks(lines: List[Tuple[Optional[int], str]]) -> List[Candidate]:
    out: List[Candidate] = []
    name: Optional[str] = None
    prev_name: Optional[str] = None       # name line directly before ``name`` (labels split across lines)
    name_page: Optional[int] = None
    gap = 0
    i = 0
    while i < len(lines):
        page, line = lines[i]
        i += 1
        if line.startswith("--- Page"):
            name, prev_name, gap = None, None, 0
            continue
        if _META_LINE_RE.match(line):
            continue                                  # method/sample lines between name and value
        if name and page == name_page and re.match(r"^\d{2,3}\s*/\s*\d{2,3}\b", line):
            # slash values (blood pressure) are two numbers, never "value + range"
            combined = f"{name}: {line}"
            if _BP_RE.search(combined):
                out += _parse_line(combined, page)
            name, gap = None, 0
            continue
        value_match = _VALUE_LINE_RE.match(line) if name else None
        if value_match and name and page == name_page:
            rest = value_match.group("rest").strip()
            flag = _FLAG_MAP.get((value_match.group("flag1") or "").lower(), "unknown")
            if rest and flag == "unknown" and (tf := _TRAILING_FLAG_RE.match(rest)) \
                    and _SIMPLE_RANGE_RE.match(tf.group("range").strip()):
                rest, flag = tf.group("range").strip(), _FLAG_MAP.get(tf.group("flag").lower(), "unknown")
            if re.fullmatch(r"(?i)H|L|HH|LL|HIGH|LOW|ABNORMAL", rest):
                flag, rest = _FLAG_MAP[rest.lower()], ""
            parts = [rest] if rest else []
            while i < len(lines) and lines[i][0] == page and _is_range_continuation(lines[i][1]):
                parts.append(lines[i][1])
                i += 1
            joined = ""
            for part in parts:
                part = re.sub(r"\s+", " ", part).strip().lstrip(",;").strip()
                wrapped = joined.count("(") > joined.count(")")       # "(Borderline" + "High)"
                joined = f"{joined} {part}" if (not joined or wrapped) else f"{joined}; {part}"
            rng = joined.strip() or None
            if rng and len(rng) > MAX_RANGE_CHARS:
                rng = rng[:MAX_RANGE_CHARS - 1].rstrip() + "…"
            combined = f"{prev_name} {name}" if prev_name else None
            if combined and canonical_name(combined):
                name = combined                       # "Glycated" + "Haemoglobin (HbA1c)"
            out += _candidate(name, value_match.group("value"), (value_match.group("unit") or "").strip(), rng,
                              flag, page, f"{name} | {line}", require_range_if_unmapped=False)
            name, prev_name, gap = None, None, 0
            continue
        if _is_name_line(line):
            prev_name = name if (name and gap == 0 and page == name_page) else None
            name, name_page, gap = line, page, 0
            continue
        prev_name = None
        gap += 1
        if gap > 1:                                   # the value must follow its name closely
            name, gap = None, 0
    return out


# ── Dates ───────────────────────────────────────────────────────────────────────

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_DATE_LABELS = [
    ("collected", r"(?:sample\s*|specimen\s*)?collect(?:ed|ion)(?:\s*(?:date|on|at|time|date\s*(?:&|and)\s*time))?"),
    ("collected", r"sample\s*(?:date|drawn(?:\s*on)?)|specimen\s*date|date\s*of\s*collection"),
    ("received", r"(?:sample\s*)?received(?:\s*(?:on|date|at|time))?"),
    ("registered", r"regist(?:ered|ration)(?:\s*(?:on|date|time|at))?"),
    ("reported", r"report(?:ed|ing)?\s*(?:date|on|at|time)|date\s*of\s*report|authori[sz]ed\s*on|released\s*on"),
    ("report_date", r"test\s*date|date"),
]
_LABEL_RE = re.compile("|".join(f"(?P<{kind}{n}>{pat})" for n, (kind, pat) in enumerate(_DATE_LABELS)), re.I)
# A date may be glued to a following time in OCR output ("02-Sep-202608:15").
_END = r"(?=\d{1,2}:\d{2}|\b)"
_ISO = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})" + _END)
_NUMERIC = re.compile(r"\b(\d{1,2})([-/.])(\d{1,2})\2(\d{4})" + _END)
_DMY_TEXT = re.compile(r"\b(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{4})" + _END)
_MDY_TEXT = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b")
KIND_LABELS = {"collected": "Collected", "received": "Received", "registered": "Registered",
               "reported": "Reported", "report_date": "Date"}
_KIND_PRIORITY = ["collected", "received", "registered", "reported", "report_date"]


def _mk(y: int, mo: int, d: int) -> Optional[date]:
    try:
        return date(y, mo, d)
    except ValueError:
        return None


@dataclass
class DateCandidate:
    kind: str                         # collected | received | registered | reported | report_date
    label: str                        # label as printed
    text: str                         # date as printed
    value: Optional[str]              # ISO date when unambiguous
    alternatives: List[str] = field(default_factory=list)  # both readings when day/month order is unknown


def _read_date(text: str, day_first: Optional[bool]) -> Optional[Tuple[str, Optional[date], List[date]]]:
    """Return (printed text, date, alternatives) for the first date in ``text``."""
    for rx in (_ISO, _DMY_TEXT, _MDY_TEXT):
        if m := rx.search(text):
            if rx is _ISO:
                d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif rx is _DMY_TEXT:
                mo = _MONTHS.get(m.group(2)[:3].lower())
                d = _mk(int(m.group(3)), mo, int(m.group(1))) if mo else None
            else:
                mo = _MONTHS.get(m.group(1)[:3].lower())
                d = _mk(int(m.group(3)), mo, int(m.group(2))) if mo else None
            if d:
                return m.group(0), d, []
    if m := _NUMERIC.search(text):
        a, b, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
        dmy, mdy = _mk(y, b, a), _mk(y, a, b)
        if a == b or not (dmy and mdy):
            return m.group(0), dmy or mdy, []
        if day_first is True:
            return m.group(0), dmy, []
        if day_first is False:
            return m.group(0), mdy, []
        return m.group(0), None, [dmy, mdy]
    return None


def _day_first(lines: List[str]) -> Optional[bool]:
    """Infer the document's numeric date order from any date that can only be read one way."""
    orders = set()
    for line in lines:
        for m in _NUMERIC.finditer(line):
            a, b = int(m.group(1)), int(m.group(3))
            if a > 12 >= b:
                orders.add(True)
            elif b > 12 >= a:
                orders.add(False)
    return orders.pop() if len(orders) == 1 else None


def parse_date(text: str) -> Tuple[Optional[date], bool]:
    """Return (date, ambiguous). Day/month order is never guessed."""
    found = _read_date(text, None)
    if not found:
        return None, False
    return found[1], bool(found[2])


def find_date_candidates(lines: List[str]) -> List[DateCandidate]:
    day_first = _day_first(lines)
    out: List[DateCandidate] = []
    seen = set()
    for line in lines:
        if re.search(r"\b(?:birth|dob|d\.o\.b)\b", line, re.I):
            continue
        matches = list(_LABEL_RE.finditer(line))
        for n, m in enumerate(matches):
            kind = re.sub(r"\d+$", "", m.lastgroup or "")
            rest = line[m.end(): matches[n + 1].start() if n + 1 < len(matches) else len(line)]
            rest = re.sub(r"^\s*[:\-]?\s*", "", rest)
            if not rest or not re.match(r"[\dA-Za-z]", rest):
                continue
            found = _read_date(rest[:40], day_first)
            if not found:
                continue
            printed, d, alts = found
            if d is None and not alts:
                continue
            key = (kind, d, tuple(alts))
            if key in seen:
                continue
            seen.add(key)
            out.append(DateCandidate(kind=kind, label=m.group(0).strip(), text=printed,
                                     value=d.isoformat() if d else None,
                                     alternatives=[a.isoformat() for a in alts]))
    out.sort(key=lambda c: _KIND_PRIORITY.index(c.kind))
    return out


def suggested_date(candidates: List[DateCandidate]) -> Optional[str]:
    """The highest-priority unambiguous candidate (still only a suggestion for the user)."""
    return next((c.value for c in candidates if c.value), None)


def find_document_date(lines: List[str]) -> Tuple[Optional[str], List[str]]:
    candidates = find_date_candidates(lines)
    best = suggested_date(candidates)
    warnings = []
    if best is None and candidates:
        warnings.append("The report date could not be read unambiguously; please choose it during review.")
    elif best is None:
        warnings.append("No report date was found; please enter it during review.")
    elif len({c.value for c in candidates if c.value}) > 1:
        warnings.append("The report shows more than one date; please choose the report date during review.")
    return best, warnings


def parse_report_text(text: str, ocr: bool = False) -> ParseResult:
    page: Optional[int] = None
    lines: List[str] = []
    paged: List[Tuple[Optional[int], str]] = []
    result = ParseResult()
    seen = set()

    def add(cand: Candidate) -> None:
        key = (cand.test_name.lower(), cand.value_text, cand.unit.lower(), cand.page)
        if key in seen:
            return
        seen.add(key)
        if ocr:
            cand.confidence = _lower(cand.confidence)
        result.candidates.append(cand)

    for raw in text.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        if pm := _PAGE_RE.match(line):
            page = int(pm.group(1))
            paged.append((page, line))
            continue
        lines.append(line)
        paged.append((page, line))
        for cand in _parse_line(line, page):
            add(cand)
    for cand in _parse_blocks(paged):
        add(cand)
    result.date_candidates = find_date_candidates(lines)
    result.document_date, result.warnings = find_document_date(lines)
    if not result.candidates:
        result.warnings.append("No laboratory values were recognised; the document text is still available.")
    return result
