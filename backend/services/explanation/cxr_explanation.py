"""Natural-language explanation of a structured chest X-ray screening result.

The language model never sees the image. It receives only the structured
output already produced by the vision model (stored server-side in
services.vision.results), and its answer is validated before release:
schema, length limits, numbers that must match the supplied model scores, and
a safety filter (no diagnosis/confirmation claims, no percentages or
disease probabilities, no treatment or medication content, no invented
patient facts). The mandatory safety statement is added by this backend, not
by the language model.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from ..text_ai.providers import TextAIUnavailable, get_text_ai_provider
from ..vision import results
from ..vision.constants import EXPECTED_TARGETS, MODEL_NAME, TARGET_LAYER, WEIGHTS_ID

logger = logging.getLogger(__name__)

EXPLANATION_SAFETY_MESSAGE = (
    "AI-generated information — not a diagnosis. Consult a qualified healthcare professional."
)

SYSTEM_PROMPT = """You are explaining an AI-generated chest X-ray screening output.
You are NOT interpreting the image independently.
Use only the structured findings and metadata supplied to you.
Do not diagnose the patient.
Do not claim that a finding is confirmed.
Do not recommend treatment or medication changes.
Do not invent measurements, symptoms, history, laboratory values, or imaging findings.
Describe model scores as model outputs, not calibrated diagnostic probabilities.
Describe Grad-CAM as a visualization of model attention/contribution, not proof of disease.
Encourage qualified clinical review.

Additional rules:
- Audience: a clinician reviewing a screening tool's output. Be concise, factual and plain.
- Never express a model score as a percentage, chance, likelihood, risk or probability of disease. Quote scores exactly as given (four decimals).
- Do not mention treatments, therapies, medications, doses or management steps at all, not even to say they are not recommended.
- Do not describe the image, anatomy seen in the image, or where the heatmap is located; you cannot see them.
- Do not describe the patient. Refer to "the model output", never to "the patient has".
- Describe scores neutrally, for example: "The model assigned a score of 0.6600 to its Cardiomegaly output."
  Never say that the image or the model indicates, shows, detects or confirms the finding, and do not call
  the score the model's confidence.
- Use score_position from the input. If the score is below the operating point, do not describe the finding
  as present, detected or likely.
- For any score, never state or imply that the finding is absent, not present, negative or ruled out.
- Other entries in highest_model_scores are model outputs, not findings present in the image.
- Explain finding names in the context of chest radiography.
- finding_explanation: what the named finding generally means in radiology terminology (general education, 1-3 sentences).
- score_explanation: what this model score represents for this multi-label model (1-3 sentences).
- gradcam_explanation: what a Grad-CAM visualization generally shows (1-3 sentences).
- limitations: 2-4 short, specific limitations of model-based screening.
- clinical_review: why qualified clinical review of the image and context is required (1-2 sentences).
- summary: 1-2 sentences. Start exactly with "The model assigned a score of <model_score> to its
  <selected_model_output> output", then say in plain words whether this is above or below the model's
  operating point of 0.5000. Never mention input field names.
Return only the JSON object."""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "finding_explanation": {"type": "string"},
        "score_explanation": {"type": "string"},
        "gradcam_explanation": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 4},
        "clinical_review": {"type": "string"},
    },
    "required": ["summary", "finding_explanation", "score_explanation",
                 "gradcam_explanation", "limitations", "clinical_review"],
    "additionalProperties": False,
}

TEXT_FIELDS = ("summary", "finding_explanation", "score_explanation", "gradcam_explanation", "clinical_review")
MAX_FIELD_CHARS = 700
MAX_LIMITATION_CHARS = 300
MAX_TOKENS = 700

_NEGATION = re.compile(r"\b(not|no|never|cannot|can't|isn't|aren't|doesn't|does not|do not|without|neither|nor)\b")

# Patterns that are always rejected.
_ALWAYS_BANNED = [
    ("percentage", re.compile(r"\d+(?:\.\d+)?\s?%|\bper\s?cent(age)?\b", re.I)),
    ("patient-claim", re.compile(r"\b(the\s+)?patient\s+(has|have|had|suffers|is\s+suffering)\b", re.I)),
    ("treatment", re.compile(r"\b(prescri\w*|medications?|medicines?|drugs?|dos(e|es|age|ing)|antibiotics?|"
                             r"diuretics?|surger(y|ies)|surgical|treat\w*|therap\w*|management\s+plan)\b", re.I)),
    ("dosing-advice", re.compile(r"\b(daily|once\s+a\s+day|twice\s+a\s+day|per\s+day|mg|mcg|tablets?|pills?|"
                                 r"capsules?|aspirin|ibuprofen|paracetamol|acetaminophen|steroids?|inhalers?|"
                                 r"oxygen\s+therapy)\b|\btake\s+(\w+\s+){0,2}(daily|once|twice|every)\b", re.I)),
    ("field-name-leak", re.compile(r"\b(score_position|selected_model_output|model_output_type|"
                                   r"is_primary_model_finding|highest_model_scores|explanation_method|"
                                   r"requires_clinical_review|primary_model_finding)\b", re.I)),
    ("invented-patient-fact", re.compile(r"\b\d+[- ]year[- ]old\b|\bthe\s+patient'?s\s+(history|symptoms?|labs?)\b", re.I)),
    ("certainty", re.compile(r"\b(definitely|certainly|undoubtedly|clearly\s+shows)\b", re.I)),
    ("absence-claim", re.compile(r"\bnot\s+(considered\s+|likely\s+|be\s+|to\s+be\s+)?present\b|\bis\s+absent\b|"
                                 r"\bnegative\s+for\b|\bruled\s+out\b|\bexclude[sd]?\s+(the\s+|a\s+)?"
                                 r"(finding|presence|diagnosis)\b", re.I)),
]
# Patterns rejected unless negated shortly before (e.g. "is not proof of disease").
_UNLESS_NEGATED = [
    ("confirmation", re.compile(r"\b(confirm\w*|diagnos(is|es|ed|e|tic)\s+of|is\s+diagnosed)\b", re.I)),
    ("proof", re.compile(r"\b(prove[sn]?|proof|proves)\b", re.I)),
    ("probability-of-disease",
     re.compile(r"\b(chances?|likelihoods?|probabilit(y|ies)|odds|risks?)\s+(of|that)\b", re.I)),
    ("presence-claim",
     re.compile(r"\b(indicat\w*|shows?|showing|reveal\w*|demonstrat\w*|detect\w*|identif\w*)\s+"
                r"(a\s+|an\s+|the\s+|this\s+)?(finding|presence|evidence)\b"
                r"|\b(output|model|score)\s+(indicates|shows|suggests|detects|reveals)\b"
                r"(?!\s+(a|the|its)\s+(model\s+)?(output\s+)?score)", re.I)),
    ("confidence-claim", re.compile(r"\bconfidence\s+(in|that|of|about)\b", re.I)),
]
_PURPOSE = re.compile(r"\b(to|help|helps|and)\s*$")  # "review is required to confirm ..."
_NUMBER = re.compile(r"(?<![\w.])(?:0|1)?\.\d{2,4}(?![\w.])")


class ExplanationSections(BaseModel):
    summary: str
    finding_explanation: str
    score_explanation: str
    gradcam_explanation: str
    limitations: List[str]
    clinical_review: str


class ExplanationSafety(BaseModel):
    message: str = EXPLANATION_SAFETY_MESSAGE
    requires_clinical_review: bool = True


class TextExplanationResponse(BaseModel):
    result_id: str
    target_pathology: str
    model_score: float
    is_primary_finding: bool
    source: str = Field("language-model", description="Explanation text generated by a language model")
    text_model: str
    generated_at: datetime
    cached: bool = False
    explanation: ExplanationSections
    safety: ExplanationSafety = Field(default_factory=ExplanationSafety)


class ExplanationNotFound(LookupError):
    """Unknown, expired or foreign screening result."""


class ExplanationUnavailable(RuntimeError):
    """The explanation could not be generated or failed validation."""


def build_context(rec: results.StoredResult, target: str) -> Dict:
    ranked = sorted(rec.scores.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "task": "Explain the selected output of an AI chest X-ray screening model for clinical review.",
        "selected_model_output": target.replace("_", " "),
        "model_score": f"{rec.scores[target]:.4f}",
        "score_position": ("at or above the model's operating point of 0.5000" if rec.scores[target] >= 0.5
                           else "below the model's operating point of 0.5000"),
        "is_primary_model_finding": target == rec.primary_pathology,
        "primary_model_finding": {"name": rec.primary_pathology.replace("_", " "),
                                  "model_score": f"{rec.scores[rec.primary_pathology]:.4f}"},
        "highest_model_scores": [{"name": p.replace("_", " "), "model_score": f"{s:.4f}"} for p, s in ranked[:3]],
        "model": MODEL_NAME,
        "weights": WEIGHTS_ID,
        "model_output_type": ("multi-label classifier with 18 independent chest X-ray pathology outputs; "
                              "each model score is between 0 and 1 and is normalized so that 0.5 is the "
                              "model's operating point; scores are not calibrated probabilities of disease"),
        "explanation_method": f"Grad-CAM on the final dense block ({TARGET_LAYER})",
        "requires_clinical_review": True,
    }


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        raise ValueError("non-string field")
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        raise ValueError("empty field")
    if len(cleaned) > limit:
        raise ValueError("field too long")
    return cleaned


def _safety_violations(text: str, allowed_numbers: List[float]) -> List[str]:
    found = [name for name, rx in _ALWAYS_BANNED if rx.search(text)]
    for name, rx in _UNLESS_NEGATED:
        for m in rx.finditer(text):
            window = text[max(0, m.start() - 40):m.start()].lower()
            if name == "confirmation" and _PURPOSE.search(window):
                continue
            if not _NEGATION.search(window):
                found.append(name)
                break
    for m in _NUMBER.finditer(text):
        value = float(m.group())
        decimals = len(m.group().split(".")[1])
        if not any(abs(round(a, decimals) - value) < 1e-9 for a in allowed_numbers):
            found.append("unsupported-number")
            break
    return found


def validate_completion(raw: str, rec: results.StoredResult) -> ExplanationSections:
    """Parse and check a model completion; raises ValueError on any problem."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    fields = {k: _clean(data.get(k), MAX_FIELD_CHARS) for k in TEXT_FIELDS}
    lims = data.get("limitations")
    if not isinstance(lims, list) or not 1 <= len(lims) <= 6:
        raise ValueError("invalid limitations")
    limitations = [_clean(x, MAX_LIMITATION_CHARS) for x in lims]
    allowed = list(rec.scores.values()) + [0.5, 0.0, 1.0]
    violations = _safety_violations(" ".join(list(fields.values()) + limitations), allowed)
    if violations:
        raise ValueError("safety: " + ",".join(sorted(set(violations))))
    return ExplanationSections(limitations=limitations, **fields)


def explain(result_id: str, owner_id: int, target: str) -> TextExplanationResponse:
    if target not in EXPECTED_TARGETS:
        raise ExplanationNotFound("Unknown model output")
    rec = results.get(result_id, owner_id)
    if rec is None:
        raise ExplanationNotFound("Screening result not found or expired")

    cached = results.get_explanation(result_id, owner_id, target)
    if cached is not None:
        return cached.model_copy(update={"cached": True})

    try:
        provider = get_text_ai_provider()
    except TextAIUnavailable as exc:
        logger.warning("Explanation provider unavailable: %s", exc)
        raise ExplanationUnavailable("Text AI provider unavailable") from exc

    user_msg = "Structured screening output (JSON):\n" + json.dumps(build_context(rec, target), indent=2)
    started = time.perf_counter()
    last_error = "no attempt"
    for attempt, temperature in enumerate((0.2, 0.0), start=1):
        prompt = user_msg if attempt == 1 else (
            user_msg + "\n\nYour previous answer broke a rule. Follow every rule exactly: do not call the score "
            "the model's confidence; do not say the output indicates, shows or detects the finding; do not say "
            "a finding is present or absent; no percentages; no treatment or medication words; no confirmation "
            "or diagnosis claims; quote scores exactly.")
        try:
            completion = provider.complete_json(SYSTEM_PROMPT, prompt, RESPONSE_SCHEMA, MAX_TOKENS, temperature)
        except TextAIUnavailable as exc:
            logger.warning("Explanation generation failed provider=%s target=%s: %s", provider.name, target, exc)
            raise ExplanationUnavailable("Text AI service unavailable") from exc
        try:
            sections = validate_completion(completion.text, rec)
        except ValueError as exc:
            last_error = str(exc)
            logger.warning("Explanation rejected provider=%s target=%s attempt=%d reason=%s",
                           provider.name, target, attempt, last_error)
            continue
        response = TextExplanationResponse(
            result_id=result_id, target_pathology=target, model_score=rec.scores[target],
            is_primary_finding=target == rec.primary_pathology, text_model=completion.model,
            generated_at=datetime.now(timezone.utc), explanation=sections)
        results.put_explanation(result_id, owner_id, target, response)
        logger.info("Explanation ok provider=%s target=%s attempts=%d ms=%.0f",
                    provider.name, target, attempt, (time.perf_counter() - started) * 1000)
        return response
    raise ExplanationUnavailable(f"Explanation failed validation ({last_error})")
