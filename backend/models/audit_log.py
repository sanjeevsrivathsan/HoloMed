from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class AuditLog(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    patient_id: Optional[int] = Field(default=None, foreign_key="patient.id", index=True)
    action: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: str | None = None

class AuditRead(SQLModel):
    id: int
    user_id: int
    patient_id: Optional[int] = None
    action: str
    timestamp: datetime
    details: str | None = None
