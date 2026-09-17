from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Report(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")
    patient_id: int | None = Field(default=None, foreign_key="patient.id")
    
    # Core metadata
    title: str = Field(default="Untitled Report")
    type: str = Field(default="Other")
    source: str = Field(default="Upload")
    report_date: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    status: str = Field(default="ready")  # uploaded, processing, extracted, needs_review, confirmed, completed, failed (legacy: ready)
    
    # Optional metadata
    hospital: Optional[str] = None
    laboratory: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    
    # File storage
    original_filename: str
    mime_type: str
    file_size: int
    storage_key: str
    storage_provider: str = "local"
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)

class ReportRead(SQLModel):
    id: int
    owner_id: int
    patient_id: int | None = None
    title: str
    type: str
    source: str
    report_date: str
    status: str
    hospital: Optional[str] = None
    laboratory: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    original_filename: str
    mime_type: str
    file_size: int
    storage_provider: str
    uploaded_at: datetime
