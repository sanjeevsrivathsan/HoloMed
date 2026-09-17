from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import datetime

class ReportSummaryBase(SQLModel):
    mode: str
    sections: str  # JSON string of ReportSummarySection[]
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ReportSummary(ReportSummaryBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    report_id: int = Field(foreign_key="report.id")
    owner_id: int = Field(foreign_key="user.id")

class ReportSummaryCreate(ReportSummaryBase):
    report_id: int

class ReportSummaryRead(ReportSummaryBase):
    id: int
    report_id: int
    owner_id: int
