"""Plain-language summary of a medical report (derived artifact).

Input to the language model is built by the backend:
- lab reports: the user-confirmed measurements only (name, value, unit, printed
  reference range, printed flag), never the raw document;
- other documents: the extracted text (truncated).

Deterministic sections (results, flagged results) are written by this module
from the confirmed data. The language model only writes an overview, general
explanations of the tests, and questions to discuss with a clinician; its output
is validated (no diagnosis/condition names, no treatment or medication content,
no result judgements, no numbers that are not in the source). The mandatory
safety notice is attached by the backend.
"""
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..text_ai.providers import TextAIUnavailable, get_text_ai_provider
from .cxr_explanation import EXPLANATION_SAFETY_MESSAGE

logger = logging.getLogger(__name__)

SAFETY_MESSAGE = EXPLANATION_SAFETY_MESSAGE
MAX_SOURCE_CHARS = 6000
MAX_TOKENS = 700
MAX_FIELD_CHARS = 900
MAX_ITEM_CHARS = 300

MODES = ("quick", "standard", "detailed", "clinical", "custom")

SYSTEM_PROMPT = """You write plain-language summaries of medical documents for the person who owns them.
Use only the information supplied. You cannot see the original document.
Rules:
- Do not diagnose. Do not name diseases or conditions (for example diabetes, anaemia or kidney disease),
  and do not say what a result means for the person's health.
- Do not judge results: never call a value high, low, elevated, raised, normal, abnormal, borderline, good, bad or concerning.
  Result flags are reported separately by the application; do not repeat or interpret them.
- Do not mention treatment, medication, supplements, diet or lifestyle changes, doses or next clinical steps.
- Do not invent values, dates, units, reference ranges, symptoms or history. Do not add numbers that are not in the input.
- Do not describe the person ("you have", "the patient has").
- overview: 1-3 neutral sentences describing what the document contains (type of report, which tests or sections).
- terms: 1-6 short general explanations of what the listed tests or medical terms measure or mean in general
  (for example "HbA1c: a blood test that reflects average blood sugar over recent months."). One per item.
- questions: 2-4 neutral questions the person could ask a qualified healthcare professional about the report.
Return only the JSON object."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "terms": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6},
        "questions": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
    },
    "required": ["overview", "terms", "questions"],
    "additionalProperties": False,
}

_NEGATION = re.compile(r"\b(not|no|never|cannot|can't|without)\b", re.I)
_BANNED = [
    ("treatment", re.compile(r"\b(prescri\w*|medications?|medicines?|drugs?|dos(e|es|age|ing)|insulin|statins?|"
                             r"metformin|supplements?|treat\w*|therap\w*|surger\w*|diet\w*|exercis\w*|"
                             r"lifestyle|tablets?|pills?)\b", re.I)),
    ("condition", re.compile(r"\b(diabet\w*|prediabet\w*|an(a)?emi\w*|leuk(a)?emi\w*|"
                             r"kidney\s+(disease|failure|damage)|renal\s+(disease|failure|impairment)|"
                             r"hyper\w+|hypo\w+|heart\s+disease|cardiovascular\s+disease|"
                             r"cancer\w*|tumou?rs?|malignan\w*|disorders?|syndromes?)\b", re.I)),
    ("judgement", re.compile(r"\b(elevated|raised|abnormal(ly)?|normal(ly)?|borderline|concern\w*|worr\w*|"
                             r"alarming|dangerous|healthy|unhealthy|out\s+of\s+range|within\s+range|"
                             r"increased|decreased|excess\w*|deficien\w*|"
                             r"(?<!-)high(?![-\s]density)|(?<!-)low(?![-\s]density))\b", re.I)),
    ("person-claim", re.compile(r"\b(you\s+(have|had|are|may\s+have)|the\s+patient\s+(has|have|had|is)|"
                                r"your\s+(condition|disease|diagnosis))\b", re.I)),
    ("certainty", re.compile(r"\b(definitely|certainly|undoubtedly|confirms?|confirmed)\b", re.I)),
]
_DIAGNOSIS = re.compile(r"\b(diagnos\w*)\b", re.I)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")


@dataclass
class SummaryMeasurement:
    test_name: str
    value_text: str
    unit: str
    reference_range: Optional[str]
    flag: str


class SummaryUnavailable(RuntimeError):
    """The text AI provider is not reachable."""


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        raise ValueError("non-string field")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned or len(cleaned) > limit:
        raise ValueError("empty or oversized field")
    return cleaned


def safety_violations(text: str, allowed_numbers: Sequence[str]) -> List[str]:
    found = [name for name, rx in _BANNED if rx.search(text)]
    for m in _DIAGNOSIS.finditer(text):
        if not _NEGATION.search(text[max(0, m.start() - 30):m.start()]):
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


def _flag_label(flag: str) -> str:
    return {"high": "marked high", "low": "marked low", "abnormal": "marked abnormal",
            "normal": "marked normal"}.get(flag, "")


def _result_line(m: SummaryMeasurement) -> str:
    line = f"{m.test_name}: {m.value_text}{(' ' + m.unit) if m.unit else ''}"
    if m.reference_range:
        line += f" (reference range printed on the report: {m.reference_range})"
    return line


def deterministic_sections(measurements: Sequence[SummaryMeasurement]) -> dict:
    results = [_result_line(m) for m in measurements]
    flagged = [f"{_result_line(m)} — {_flag_label(m.flag)} by the laboratory"
               for m in measurements if m.flag in ("high", "low", "abnormal")]
    marked_normal = [_result_line(m) for m in measurements if m.flag == "normal"]
    unflagged = [m for m in measurements if m.flag == "unknown"]
    flagged_text = "\n".join(flagged) if flagged else "No results are marked as outside a range in the report."
    if unflagged:
        flagged_text += ("\nSome results carry no flag in the report; HoloMed does not judge them. "
                         "Discuss them with a qualified healthcare professional.")
    return {
        "findings": "\n".join(results) if results else "No confirmed measurements for this report.",
        "abnormal": flagged_text,
        "normal": "\n".join(marked_normal) if marked_normal else "No results are marked as normal in the report.",
    }


def build_prompt(title: str, report_type: str, report_date: str,
                 measurements: Sequence[SummaryMeasurement], text: Optional[str]) -> str:
    payload = {"document_title": title, "document_type": report_type, "document_date": report_date[:10]}
    if measurements:
        payload["tests"] = [{"name": m.test_name, "value": m.value_text, "unit": m.unit} for m in measurements]
    if text:
        payload["document_text"] = text[:MAX_SOURCE_CHARS]
    return "Document information (JSON):\n" + json.dumps(payload, indent=2, ensure_ascii=False)


def validate_completion(raw: str, allowed_numbers: Sequence[str]) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("not an object")
    overview = _clean(data.get("overview"), MAX_FIELD_CHARS)
    terms, questions = data.get("terms"), data.get("questions")
    if not isinstance(terms, list) or not 1 <= len(terms) <= 8:
        raise ValueError("invalid terms")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 6:
        raise ValueError("invalid questions")
    terms = [_clean(t, MAX_ITEM_CHARS) for t in terms]
    questions = [_clean(q, MAX_ITEM_CHARS) for q in questions]
    violations = safety_violations(" ".join([overview] + terms + questions), allowed_numbers)
    if violations:
        raise ValueError("safety: " + ",".join(sorted(set(violations))))
    return {"executive": overview, "terms": "\n".join(terms), "questions": "\n".join(questions)}


LABELS = {
    "executive": "Overview",
    "findings": "Confirmed results",
    "abnormal": "Results flagged in the report",
    "normal": "Results marked normal in the report",
    "terms": "What these tests measure",
    "questions": "Questions to ask your clinician",
}
MODE_SECTIONS = {
    "quick": ("executive", "abnormal"),
    "standard": ("executive", "findings", "abnormal", "terms", "questions"),
    "detailed": ("executive", "findings", "abnormal", "normal", "terms", "questions"),
    "clinical": ("executive", "findings", "abnormal", "normal"),
    "custom": ("executive", "findings", "abnormal", "normal", "terms", "questions"),
}


@dataclass
class SummaryResult:
    sections: List[dict]
    text_model: str
    generator: str       # "language-model"
    elapsed_ms: float


def generate(title: str, report_type: str, report_date: str, measurements: Sequence[SummaryMeasurement],
             text: Optional[str], mode: str) -> SummaryResult:
    if mode not in MODES:
        mode = "standard"
    try:
        provider = get_text_ai_provider()
    except TextAIUnavailable as exc:
        raise SummaryUnavailable("Text AI provider unavailable") from exc

    source_text = text if not measurements else None
    user_msg = build_prompt(title, report_type, report_date, measurements, source_text)
    allowed = _numbers_in(title, report_date, source_text or "",
                          *[f"{m.test_name} {m.value_text} {m.reference_range or ''}" for m in measurements])
    started = time.perf_counter()
    last_error = "no attempt"
    for attempt, temperature in enumerate((0.2, 0.0), start=1):
        prompt = user_msg if attempt == 1 else (
            user_msg + "\n\nYour previous answer broke a rule. Do not name conditions, do not judge any value "
            "(no high/low/normal/elevated), no treatment or lifestyle words, and add no numbers.")
        try:
            completion = provider.complete_json(SYSTEM_PROMPT, prompt, RESPONSE_SCHEMA, MAX_TOKENS, temperature)
        except TextAIUnavailable as exc:
            logger.warning("Report summary provider unavailable provider=%s: %s", provider.name, exc)
            raise SummaryUnavailable("Text AI service unavailable") from exc
        try:
            ai_sections = validate_completion(completion.text, allowed)
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Report summary rejected provider=%s attempt=%d reason=%s", provider.name, attempt,
                           last_error)
            continue
        content = {**deterministic_sections(measurements), **ai_sections}
        if not measurements:
            content.pop("findings"), content.pop("abnormal"), content.pop("normal")
        wanted = MODE_SECTIONS[mode]
        sections = [{"key": key, "label": LABELS[key], "content": content[key], "visible": True}
                    for key in wanted if key in content]
        elapsed = (time.perf_counter() - started) * 1000
        logger.info("Report summary ok provider=%s attempts=%d ms=%.0f", provider.name, attempt, elapsed)
        return SummaryResult(sections=sections, text_model=completion.model, generator="language-model",
                             elapsed_ms=round(elapsed, 1))
    raise ValueError(f"summary failed validation ({last_error})")
