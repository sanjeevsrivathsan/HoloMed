from __future__ import annotations
from sqlmodel import SQLModel, Field

class StorageConnectionBase(SQLModel):
    provider: str
    label: str
    status: str = "not_connected"
    is_primary: bool = False
    description: str = ""

class StorageConnection(StorageConnectionBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id")

class StorageConnectionCreate(StorageConnectionBase):
    pass

class StorageConnectionRead(StorageConnectionBase):
    id: int
    owner_id: int
