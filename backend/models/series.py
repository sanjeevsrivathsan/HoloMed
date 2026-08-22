from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional

class Series(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    study_id: int = Field(foreign_key="study.id")
    owner_id: int = Field(index=True)
    series_instance_uid: str = Field(index=True)
    modality: str | None = None
