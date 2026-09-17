from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import date
from typing import Optional

class MeasurementBase(SQLModel):
    test_name: str
    value: float
    unit: str
    reference_range: Optional[str] = None
    flag: str = "unknown"
    report_date: date
    hospital: Optional[str] = None
    laboratory: Optional[str] = None
    department: Optional[str] = None
    comments: Optional[str] = None
    source_location: Optional[str] = None
    
    # Optional relation to a report
    report_id: Optional[int] = Field(default=None, foreign_key="report.id")

class MedicalMeasurement(MeasurementBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id")
    owner_id: int = Field(foreign_key="user.id")

class MeasurementCreate(MeasurementBase):
    patient_id: int

class MeasurementRead(MeasurementBase):
    id: int
    patient_id: int
    owner_id: int
