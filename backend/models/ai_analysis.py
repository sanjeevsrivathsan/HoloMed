from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AIAnalysis(SQLModel, table=True):
    """One chest X-ray screening run, kept so the result can be reopened.

    Scores are model outputs, not diagnoses. `response_json` is the screening response
    exactly as returned (findings, Grad-CAM metadata and rendered images).
    """
    __tablename__ = "ai_analysis"

    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(default_factory=lambda: str(uuid.uuid4()), index=True, unique=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    study_id: Optional[int] = Field(default=None, foreign_key="study.id", index=True)
    instance_id: Optional[int] = Field(default=None, foreign_key="instance.id")
    input_format: str
    input_sha256: str
    provider: str
    model_name: str
    model_weights: str
    weight_sha256: str
    primary_pathology: str
    primary_score: float
    selected_target: Optional[str] = None
    response_json: str
    text_explanations_json: str = "{}"
    result_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
