from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    action: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: str | None = None

class AuditRead(SQLModel):
    id: int
    user_id: int
    action: str
    timestamp: datetime
    details: str | None = None
