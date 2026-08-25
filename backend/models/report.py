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
    status: str = Field(default="ready")  # ready, processing, extracting, ocr, failed, uploading
    
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
