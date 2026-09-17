from __future__ import annotations
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class User(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    hashed_password: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    google_id: Optional[str] = Field(default=None, unique=True, index=True)
