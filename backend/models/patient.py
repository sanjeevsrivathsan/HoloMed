from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def new_patient_uid() -> str:
    return str(uuid.uuid4())


class Patient(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("owner_id", "patient_code", name="uq_patient_owner_code"),)

    # Integer primary key stays the relational key (studies, reports, measurements reference it);
    # `uid` is the immutable identifier exposed by the API and never reused.
    id: int | None = Field(default=None, primary_key=True)
    uid: Optional[str] = Field(default_factory=new_patient_uid, index=True, unique=True)
    owner_id: int = Field(index=True)
    patient_code: Optional[str] = Field(default=None, index=True)
    external_id: str | None = Field(default=None, index=True)
    display_name: str
    date_of_birth: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[int] = None
    phone: Optional[str] = None
    created_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow)
