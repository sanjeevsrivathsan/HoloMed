from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Study(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id", index=True)
    owner_id: int = Field(index=True)
    study_instance_uid: str = Field(index=True)
    modality: str | None = None
    description: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
