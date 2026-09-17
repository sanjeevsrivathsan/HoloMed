import os
from sqlmodel import SQLModel, create_engine, Session

DB_PATH = os.getenv("HOLUMED_DB_PATH", "./data/holomed.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

def init_db() -> None:
    """Create database tables if they don't exist."""
    SQLModel.metadata.create_all(engine)

from typing import Generator

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
