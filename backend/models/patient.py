from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional

class Patient(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(index=True)
    external_id: str | None = Field(default=None, index=True)
    display_name: str
