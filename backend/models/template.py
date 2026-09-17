from __future__ import annotations
from sqlmodel import SQLModel, Field
from datetime import datetime
from typing import Optional

class TemplateBase(SQLModel):
    name: str
    category: str
    description: str
    sections: str  # JSON string of TemplateSection[]
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Template(TemplateBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")

class TemplateCreate(TemplateBase):
    pass

class TemplateRead(TemplateBase):
    id: int
    owner_id: int
