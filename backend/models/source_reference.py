from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class SourceReference(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    report_id: str = Field(index=True)
    type: str
    storage_provider: str
    storage_location: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
