"""Response schemas for the vision screening API.

Pure pydantic — importing this module does not import torch.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

SAFETY_MESSAGE = (
    "AI-generated screening assistance — not a diagnostic determination. "
    "Consult a qualified healthcare professional."
)
SCORE_SEMANTICS = (
    "Model score from TorchXRayVision (sigmoid followed by per-output operating-point "
    "normalization; 0.5 corresponds to the model's operating point). It is not a "
    "calibrated clinical probability and not a diagnosis."
)
EXPLANATION_DESCRIPTION = (
    "Grad-CAM visual explanation: highlights image regions that most influenced the "
    "selected model output. It is an attention visualization, not proof or localization "
    "of disease, and requires clinical review."
)


class VisionModelInfo(BaseModel):
    name: str
    architecture: str
    weights: str
    weight_sha256: str
    targets: int
    target_list: List[str]
    device: str
    input_size: int
    score_semantics: str = SCORE_SEMANTICS


class VisionInputInfo(BaseModel):
    """Technical, non-identifying description of the uploaded image."""
    format: Literal["png", "jpeg", "dicom"]
    width: int
    height: int
    source_mode: str = Field(description="PIL mode or DICOM PhotometricInterpretation")
    bits_stored: Optional[int] = None
    modality: Optional[str] = None
    transfer_syntax: Optional[str] = None
    preprocessing: List[str]


class VisionFinding(BaseModel):
    pathology: str
    score: float = Field(ge=0.0, le=1.0, description="Model score (not a calibrated probability)")


class EncodedImage(BaseModel):
    media_type: Literal["image/png"] = "image/png"
    encoding: Literal["base64"] = "base64"
    width: int
    height: int
    data: str


class VisionExplanation(BaseModel):
    method: Literal["Grad-CAM"] = "Grad-CAM"
    target_pathology: str
    target_score: float
    target_layer: str
    description: str = EXPLANATION_DESCRIPTION
    original: EncodedImage = Field(
        description="Grayscale center-cropped region the model analyzed; heatmap and overlay align to it")
    heatmap: EncodedImage
    overlay: EncodedImage


class VisionTiming(BaseModel):
    preprocessing_ms: float
    inference_ms: float
    gradcam_ms: float
    rendering_ms: float
    total_ms: float


class VisionSafety(BaseModel):
    message: str = SAFETY_MESSAGE
    requires_clinical_review: bool = True


class VisionScreenResponse(BaseModel):
    model: VisionModelInfo
    input: VisionInputInfo
    primary_finding: VisionFinding
    findings: List[VisionFinding] = Field(description="All model outputs, highest score first")
    explanation: VisionExplanation
    timing: VisionTiming
    inferred_at: datetime
    safety: VisionSafety = Field(default_factory=VisionSafety)

    model_config = {"protected_namespaces": ()}
