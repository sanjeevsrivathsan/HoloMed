from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    original_filename: str
    mime_type: str
    file_size: int
    storage_key: str
    storage_provider: str = "local"
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
