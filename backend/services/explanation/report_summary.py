"""Plain-language summary of a medical report (derived artifact).

One structured pathway for every report:

    confirmed measurements + report metadata (+ earlier confirmed results) → summary

Deterministic sections are written by this module from confirmed data: report overview,
confirmed results, results flagged by the laboratory, changes since earlier confirmed
results, data limitations and provenance. The language model only writes a short
narrative, general explanations of the tests and questions for a clinician. It receives
test names, values, units and the laboratory's printed flags — never the raw document
(except for non-laboratory documents without values, which use the extracted text).
Its output is validated: no diagnosis or condition names, no treatment or lifestyle
advice, no judgement of values beyond repeating a laboratory flag, no numbers that are
not in the source. Clinical mode needs no language model. The mandatory safety notice
is attached by the backend.
"""
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence

from ..text_ai.providers import TextAIUnavailable, get_text_ai_provider
from .cxr_explanation import EXPLANATION_SAFETY_MESSAGE

logger = logging.getLogger(__name__)

SAFETY_MESSAGE = EXPLANATION_SAFETY_MESSAGE
MAX_SOURCE_CHARS = 6000
MAX_FIELD_CHARS = 1200
MAX_ITEM_CHARS = 320

MODES = ("quick", "standard", "detailed", "clinical", "custom")


# ── Input ──────────────────────────────────────────────────────────────────────

@dataclass
class SummaryMeasurement:
    test_name: str
    value_text: str
    unit: str
    reference_range: Optional[str]
    flag: str
    page: Optional[int] = None


@dataclass
class HistoryPoint:
    value: float
    value_text: str
    unit: str
    report_date: str           # ISO
    report_title: str


@dataclass
class SummaryInput:
    title: str
    report_type: str
    report_date: str                                   # ISO (date part used)
    date_confirmed: bool = True
    laboratory: Optional[str] = None
    source_filename: Optional[str] = None
    measurements: List[SummaryMeasurement] = field(default_factory=list)
    values: Dict[str, float] = field(default_factory=dict)               # test_name → numeric value
    history: Dict[str, List[HistoryPoint]] = field(default_factory=dict)  # earlier confirmed results
    pending_count: int = 0
    ignored_count: int = 0
    extraction_method: Optional[str] = None
    extraction_quality: Optional[str] = None
    text: Optional[str] = None                          # only for documents without values


class SummaryUnavailable(RuntimeError):
    """The text AI provider is not reachable."""


# ── Deterministic content ──────────────────────────────────────────────────────

CATEGORIES = [
    ("Lipid profile", r"cholesterol|triglycer|\bhdl\b|\bldl\b|vldl|lipoprotein"),
    ("Blood glucose", r"glucose|sugar|hba1c|a1c"),
    ("Liver function", r"bilirubin|sgot|sgpt|\bast\b|\balt\b|alkaline\s+phosphatase|\balp\b|ggt|gamma|"
                       r"albumin|globulin|total\s+protein|a/g"),
    ("Kidney function", r"creatinine|urea|\bbun\b|uric\s+acid|egfr"),
    ("Blood count", r"ha?emoglobin|\bhb\b|wbc|leu[ck]ocyte|platelet|\brbc\b|ha?ematocrit|\bpcv\b|\bmcv\b|\bmch"),
    ("Thyroid", r"\btsh\b|\bt3\b|\bt4\b|thyro"),
    ("Vitamins", r"vitamin"),
    ("Blood pressure", r"blood\s+pressure"),
]
_METHOD_LABELS = {"pdf_text": "PDF text layer", "ocr": "OCR (scanned document)", "pdf_text+ocr": "PDF text layer + OCR"}
_FLAG_WORDS = {"high": "marked high", "low": "marked low", "abnormal": "marked abnormal", "normal": "marked normal"}


def category(test_name: str) -> Optional[str]:
    for label, pattern in CATEGORIES:
        if re.search(pattern, test_name, re.I):
            return label
    return None


def _date_text(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return iso


def _value(m: SummaryMeasurement) -> str:
    return f"{m.value_text}{(' ' + m.unit) if m.unit else ''}"


def _type_label(report_type: str) -> str:
    return {"Blood Test": "Blood test / laboratory report", "Imaging Report": "Radiology report"}.get(
        report_type, report_type)


def _categories(ms: Sequence[SummaryMeasurement]) -> List[str]:
    found = []
    for m in ms:
        c = category(m.test_name)
        if c and c not in found:
            found.append(c)
    return found


def overview_section(inp: SummaryInput) -> str:
    ms = inp.measurements
    date_part = _date_text(inp.report_date) + ("" if inp.date_confirmed else " (date not yet confirmed)")
    lines = [f"{_type_label(inp.report_type)} dated {date_part}"
             + (f", {inp.laboratory}" if inp.laboratory else "") + "."]
    if ms:
        cats = _categories(ms)
        other = sum(1 for m in ms if category(m.test_name) is None)
        cat_text = ", ".join(cats) + (f" and {other} other test(s)" if cats and other else "")
        lines.append(f"{len(ms)} confirmed result(s)" + (f" covering {cat_text}." if cats else "."))
        flagged = [m for m in ms if m.flag in ("high", "low", "abnormal")]
        lines.append(f"{len(flagged)} result(s) are flagged by the laboratory." if flagged
                     else "No confirmed result carries a laboratory flag.")
    else:
        lines.append("No measurements have been confirmed for this document.")
    return "\n".join(lines)


def results_section(inp: SummaryInput, style: str) -> str:
    out = []
    for m in inp.measurements:
        flag = _FLAG_WORDS.get(m.flag)
        if style == "compact":
            out.append(f"{m.test_name}: {_value(m)}" + (f" ({flag})" if flag else ""))
        elif style == "clinical":
            parts = [m.test_name, _value(m), f"ref {m.reference_range}" if m.reference_range else "ref not printed",
                     flag or "no flag", _date_text(inp.report_date)]
            if m.page:
                parts.append(f"p.{m.page}")
            out.append(" | ".join(parts))
        else:
            line = f"{m.test_name}: {_value(m)}"
            line += (f" — reference range printed on the report: {m.reference_range}" if m.reference_range
                     else " — no reference range printed")
            if flag:
                line += f" — {flag} by the laboratory"
            if style == "detailed" and m.page:
                line += f" (page {m.page})"
            out.append(line)
    return "\n".join(out)


def flagged_section(inp: SummaryInput) -> str:
    flagged = [f"{m.test_name}: {_value(m)} — {_FLAG_WORDS[m.flag]} by the laboratory"
               + (f" (printed range: {m.reference_range})" if m.reference_range else "")
               for m in inp.measurements if m.flag in ("high", "low", "abnormal")]
    text = "\n".join(flagged) if flagged else "No confirmed result is marked as outside a range in the report."
    if any(m.flag == "unknown" for m in inp.measurements):
        text += ("\nResults without a printed flag are shown as printed; HoloMed does not judge them. "
                 "Discuss them with a qualified healthcare professional.")
    return text


def normal_section(inp: SummaryInput) -> str:
    marked = [f"{m.test_name}: {_value(m)}" for m in inp.measurements if m.flag == "normal"]
    return "\n".join(marked) if marked else "No confirmed result is explicitly marked normal in the report."


def trends_section(inp: SummaryInput) -> str:
    lines = []
    for m in inp.measurements:
        current = inp.values.get(m.test_name)
        points = [p for p in inp.history.get(m.test_name, []) if p.unit == m.unit]
        if current is None or not points:
            continue
        prev = points[-1]
        delta = current - prev.value
        sign = "+" if delta > 0 else ""
        lines.append(f"{m.test_name}: {_value(m)} on {_date_text(inp.report_date)}; previously {prev.value_text} "
                     f"{m.unit} on {_date_text(prev.report_date)} (change {sign}{delta:g} {m.unit})".rstrip()
                     + (f"; {len(points)} earlier confirmed result(s) in total" if len(points) > 1 else ""))
    return "\n".join(lines)


def limitations_section(inp: SummaryInput) -> str:
    notes = []
    if not inp.date_confirmed:
        notes.append("The report date has not been confirmed.")
    if inp.pending_count:
        notes.append(f"{inp.pending_count} extracted value(s) have not been confirmed and are not included.")
    if inp.ignored_count:
        notes.append(f"{inp.ignored_count} extracted value(s) were ignored during review and are not included.")
    missing = [m.test_name for m in inp.measurements if not m.reference_range]
    if missing:
        notes.append("No reference range is printed for: " + ", ".join(missing) + ".")
    if inp.extraction_method and inp.extraction_method != "pdf_text":
        notes.append("Some text was read with OCR; values were checked by you during review.")
    notes.append("Only information printed in the report and confirmed by you is used; nothing is inferred.")
    return "\n".join(notes)


def provenance_section(inp: SummaryInput) -> str:
    lines = [f"Source document: {inp.source_filename or inp.title} (original stored unchanged)."]
    if inp.extraction_method:
        lines.append(f"Values extracted from the {_METHOD_LABELS.get(inp.extraction_method, inp.extraction_method)} "
                     "and confirmed by the user.")
    lines.append("Report date " + ("confirmed by the user." if inp.date_confirmed else "not yet confirmed."))
    return "\n".join(lines)


def extraction_section(inp: SummaryInput) -> str:
    lines = []
    if inp.extraction_method:
        lines.append(f"Extraction method: {_METHOD_LABELS.get(inp.extraction_method, inp.extraction_method)}"
                     + (" (lower reliability; check against the original)"
                        if inp.extraction_quality == "low" else "") + ".")
    pages = sorted({m.page for m in inp.measurements if m.page})
    if pages:
        lines.append("Confirmed values come from page(s) " + ", ".join(str(p) for p in pages) + ".")
    lines.append(f"{len(inp.measurements)} confirmed, {inp.pending_count} not yet confirmed, "
                 f"{inp.ignored_count} ignored.")
    return "\n".join(lines)


# ── Language model part ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You write plain-language summaries of medical documents for the person who owns them.
Use only the information supplied. You cannot see the original document.
Rules:
- Do not diagnose. Do not name diseases or conditions (for example diabetes, anaemia or kidney disease),
  and do not say what a result means for the person's health.
- Do not judge results: never call a value high, low, elevated, raised, normal, abnormal, borderline, good, bad or
  concerning. When a test has a report_flag, you may say that the laboratory marked it (for example
  "the laboratory marked LDL high"), without explaining what that means for health.
- Do not mention treatment, medication, supplements, diet or lifestyle changes, doses or next clinical steps.
- Do not invent values, dates, units, reference ranges, symptoms or history. Only use numbers from the input.
- Do not describe the person ("you have", "the patient has").
- overview: {overview_len} neutral sentences: what kind of report this is, its date, which groups of tests it
  contains, and which tests the laboratory marked (if any).
- terms: {terms_len} short general explanations of what the listed tests measure, one per test or test group,
  using the test names from the input (for example "HbA1c: a blood test that reflects average blood sugar over
  recent months.").
- questions: {questions_len} specific, neutral questions the person could ask a qualified healthcare
  professional about the tests in this report (mention the test names).
Return only the JSON object."""

MODE_AI = {
    "quick": {"overview_len": "1-2", "terms_len": "1-3", "questions_len": "1-2", "terms_max": 3, "questions_max": 2,
              "tokens": 450},
    "standard": {"overview_len": "2-3", "terms_len": "3-6", "questions_len": "3-4", "terms_max": 6,
                 "questions_max": 4, "tokens": 800},
    "detailed": {"overview_len": "3-4", "terms_len": "one explanation for each listed test, up to 12,",
                 "questions_len": "4-5", "terms_max": 12, "questions_max": 5, "tokens": 1400},
}
MODE_AI["custom"] = MODE_AI["detailed"]


def _schema(terms_max: int, questions_max: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "overview": {"type": "string"},
            "terms": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": terms_max},
            "questions": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": questions_max},
        },
        "required": ["overview", "terms", "questions"],
        "additionalProperties": False,
    }


RESPONSE_SCHEMA = _schema(6, 4)

_NEGATION = re.compile(r"\b(not|no|never|cannot|can't|without)\b", re.I)
_BANNED = [
    ("treatment", re.compile(r"\b(prescri\w*|medications?|medicines?|drugs?|dos(e|es|age|ing)|insulin|statins?|"
                             r"metformin|supplements?|treat\w*|therap\w*|surger\w*|diet\w*|exercis\w*|"
                             r"lifestyle|tablets?|pills?)\b", re.I)),
    ("condition", re.compile(r"\b(diabet\w*|prediabet\w*|an(a)?emi\w*|leuk(a)?emi\w*|"
                             r"kidney\s+(disease|failure|damage)|renal\s+(disease|failure|impairment)|"
                             r"liver\s+(disease|damage|failure)|fatty\s+liver|cirrhosis|hepatitis|"
                             r"hyper\w+|hypo\w+|heart\s+disease|cardiovascular\s+disease|"
                             r"cancer\w*|tumou?rs?|malignan\w*|disorders?|syndromes?)\b", re.I)),
    ("judgement", re.compile(r"\b(elevated|raised|abnormal(ly)?|normal(ly)?|borderline|concern\w*|worr\w*|"
                             r"alarming|dangerous|healthy|unhealthy|out\s+of\s+range|within\s+range|"
                             r"increased|decreased|excess\w*|deficien\w*|"
                             r"(?<!-)high(?![-\s]density)|(?<!-)low(?![-\s]density))\b", re.I)),
    ("person-claim", re.compile(r"\b(you\s+(have|had|are|may\s+have)|the\s+patient\s+(has|have|had|is)|"
                                r"your\s+(condition|disease|diagnosis))\b", re.I)),
    ("certainty", re.compile(r"\b(definitely|certainly|undoubtedly|confirms|confirmed\s+(?:diagnosis|condition|"
                             r"disease))\b", re.I)),
]
# Repeating a laboratory flag is allowed ("the laboratory marked LDL high"); it is removed before the checks.
_ALLOWED_FLAG_PHRASE = re.compile(
    r"\b(?:mark(?:ed|ing)|flag(?:ged|ging)|label(?:l?ed|l?ing))\s+(?:[\w()/-]+,?\s+){0,12}?(?:as\s+)?(?:high|low|abnormal|normal)\b"
    r"|\b(?:marked|flagged)\b", re.I)
_DIAGNOSIS = re.compile(r"\b(diagnos\w*)\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        raise ValueError("non-string field")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned or len(cleaned) > limit:
        raise ValueError("empty or oversized field")
    return cleaned


def safety_violations(text: str, allowed_numbers: Sequence[str]) -> List[str]:
    checked = _ALLOWED_FLAG_PHRASE.sub(" ", text)
    found = [name for name, rx in _BANNED if rx.search(checked)]
    for m in _DIAGNOSIS.finditer(checked):
        if not _NEGATION.search(checked[max(0, m.start() - 30):m.start()]):
            found.append("diagnosis")
            break
    allowed = {a.replace(",", ".").lstrip("0") or "0" for a in allowed_numbers}
    for m in _NUMBER.finditer(text):
        token = m.group().replace(",", ".")
        norm = token.lstrip("0") or "0"
        if norm not in allowed and token not in {"1", "2", "3"}:
            found.append("unsupported-number")
            break
    return found


def _numbers_in(*texts: str) -> List[str]:
    out: List[str] = []
    for t in texts:
        out += [m.group() for m in _NUMBER.finditer(t or "")]
    return out


def build_prompt(inp: SummaryInput) -> str:
    payload = {
        "document_type": _type_label(inp.report_type),
        "document_date": inp.report_date[:10],
        "test_groups": _categories(inp.measurements),
    }
    if inp.measurements:
        tests = []
        for m in inp.measurements:
            item = {"name": m.test_name, "value": m.value_text, "unit": m.unit}
            if m.flag in ("high", "low", "abnormal"):
                item["report_flag"] = f"marked {m.flag} by the laboratory"
            tests.append(item)
        payload["tests"] = tests
    if inp.text and not inp.measurements:
        payload["document_text"] = inp.text[:MAX_SOURCE_CHARS]
    return "Document information (JSON):\n" + json.dumps(payload, indent=2, ensure_ascii=False)


def allowed_numbers(inp: SummaryInput) -> List[str]:
    numbers = _numbers_in(inp.title, inp.report_date, inp.text or "", _date_text(inp.report_date),
                          *[f"{m.test_name} {m.value_text} {m.unit} {m.reference_range or ''}" for m in inp.measurements])
    numbers += [str(len(inp.measurements)), str(len(_categories(inp.measurements)))]
    return numbers


def validate_completion(raw: str, allowed: Sequence[str]) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("not an object")
    overview = _clean(data.get("overview"), MAX_FIELD_CHARS)
    terms, questions = data.get("terms"), data.get("questions")
    if not isinstance(terms, list) or not 1 <= len(terms) <= 14:
        raise ValueError("invalid terms")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 6:
        raise ValueError("invalid questions")
    terms = [_clean(t, MAX_ITEM_CHARS) for t in terms]
    questions = [_clean(q, MAX_ITEM_CHARS) for q in questions]
    violations = safety_violations(" ".join([overview] + terms + questions), allowed)
    if violations:
        raise ValueError("safety: " + ",".join(sorted(set(violations))))
    return {"executive": overview, "terms": "\n".join(terms), "questions": "\n".join(questions)}


# ── Assembly ────────────────────────────────────────────────────────────────────

LABELS = {
    "overview": "Report overview",
    "executive": "Summary",
    "findings": "Confirmed results",
    "abnormal": "Results flagged in the report",
    "normal": "Results marked normal in the report",
    "terms": "What these tests measure",
    "trends": "Changes since earlier confirmed results",
    "questions": "Questions to ask your clinician",
    "extraction": "Extraction notes",
    "limitations": "Data limitations",
    "provenance": "Source and provenance",
}
AI_SECTIONS = {"executive", "terms", "questions"}
MODE_SECTIONS = {
    "quick": ("executive", "findings", "abnormal"),
    "standard": ("overview", "executive", "findings", "abnormal", "terms", "trends", "questions", "limitations"),
    "detailed": ("overview", "executive", "findings", "abnormal", "normal", "terms", "trends", "questions",
                 "extraction", "limitations"),
    "clinical": ("overview", "findings", "abnormal", "trends", "provenance", "limitations"),
    "custom": ("overview", "executive", "findings", "abnormal", "normal", "terms", "trends", "questions",
               "extraction", "limitations", "provenance"),
}
RESULT_STYLE = {"quick": "compact", "standard": "standard", "detailed": "detailed", "clinical": "clinical",
                "custom": "detailed"}
LAB_ONLY_SECTIONS = {"findings", "abnormal", "normal", "trends", "extraction"}


@dataclass
class SummaryResult:
    sections: List[dict]
    text_model: Optional[str]
    generator: str       # "language-model" | "structured-data"
    elapsed_ms: float


def _deterministic(inp: SummaryInput, mode: str) -> Dict[str, str]:
    content = {
        "overview": overview_section(inp),
        "findings": results_section(inp, RESULT_STYLE[mode]),
        "abnormal": flagged_section(inp),
        "normal": normal_section(inp),
        "trends": trends_section(inp),
        "extraction": extraction_section(inp),
        "limitations": limitations_section(inp),
        "provenance": provenance_section(inp),
    }
    if not inp.measurements:
        for key in LAB_ONLY_SECTIONS:
            content.pop(key)
    return {k: v for k, v in content.items() if v}


def _generate_ai(inp: SummaryInput, mode: str) -> tuple:
    settings = MODE_AI[mode]
    try:
        provider = get_text_ai_provider()
    except TextAIUnavailable as exc:
        raise SummaryUnavailable("Text AI provider unavailable") from exc
    system = SYSTEM_PROMPT.format(**settings)
    schema = _schema(settings["terms_max"], settings["questions_max"])
    user_msg = build_prompt(inp)
    allowed = allowed_numbers(inp)
    last_error = "no attempt"
    for attempt, temperature in enumerate((0.2, 0.0), start=1):
        prompt = user_msg if attempt == 1 else (
            user_msg + "\n\nYour previous answer broke a rule. Do not name conditions, do not judge any value "
            "(only say that the laboratory marked a test when report_flag is given), no treatment or lifestyle "
            "words, and add no numbers.")
        try:
            completion = provider.complete_json(system, prompt, schema, settings["tokens"], temperature)
        except TextAIUnavailable as exc:
            logger.warning("Report summary provider unavailable provider=%s: %s", provider.name, exc)
            raise SummaryUnavailable("Text AI service unavailable") from exc
        try:
            return validate_completion(completion.text, allowed), completion.model, attempt
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Report summary rejected provider=%s attempt=%d reason=%s", provider.name, attempt,
                           last_error)
    raise ValueError(f"summary failed validation ({last_error})")


def generate(inp: SummaryInput, mode: str) -> SummaryResult:
    if mode not in MODES:
        mode = "standard"
    started = time.perf_counter()
    content = _deterministic(inp, mode)
    wanted = MODE_SECTIONS[mode]
    model, attempts = None, 0
    if AI_SECTIONS & set(wanted):
        ai, model, attempts = _generate_ai(inp, mode)
        content.update(ai)
    sections = [{"key": key, "label": LABELS[key], "content": content[key], "visible": True,
                 "source": "ai" if key in AI_SECTIONS else "data"}
                for key in wanted if content.get(key)]
    elapsed = round((time.perf_counter() - started) * 1000, 1)
    logger.info("Report summary ok mode=%s ai=%s attempts=%d ms=%.0f", mode, bool(model), attempts, elapsed)
    return SummaryResult(sections=sections, text_model=model,
                         generator="language-model" if model else "structured-data", elapsed_ms=elapsed)
