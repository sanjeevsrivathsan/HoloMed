from __future__ import annotations

from pydantic import BaseModel
from typing import Optional

class StudyMeta(BaseModel):
    """Schema for QIDO‑RS Study search results.

    Only non‑PHI fields are exposed. ``CreatedDate`` is an ISO‑8601 timestamp string.
    """

    StudyInstanceUID: str
    Modality: Optional[str] = None
    CreatedDate: Optional[str] = None
    Description: Optional[str] = None

    class Config:
        orm_mode = True

class SeriesMeta(BaseModel):
    """Schema for QIDO‑RS Series search results."""

    SeriesInstanceUID: str
    Modality: Optional[str] = None

    class Config:
        orm_mode = True

class InstanceMeta(BaseModel):
    """Schema for QIDO‑RS Instance search results."""

    SOPInstanceUID: str

    class Config:
        orm_mode = True
