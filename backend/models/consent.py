from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import date
from typing import Optional

class ConsentBase(SQLModel):
    recipient: str
    purpose: str
    scope: str
    issued_date: date
    expiry_date: date
    revoked: bool = False

class ConsentRecord(ConsentBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    patient_id: int = Field(foreign_key="patient.id")
    owner_id: int = Field(foreign_key="user.id")

class ConsentCreate(ConsentBase):
    patient_id: int

class ConsentRead(ConsentBase):
    id: int
    patient_id: int
    owner_id: int
