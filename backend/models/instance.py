from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional

class Instance(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    series_id: int = Field(foreign_key="series.id")
    owner_id: int = Field(index=True)
    sop_instance_uid: str = Field(index=True)
    storage_key: str
    storage_provider: str = "local"
