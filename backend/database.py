import logging
import os
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine, Session

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("HOLUMED_DB_PATH", "./data/holomed.db")

engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

def init_db() -> None:
    """Create database tables if they don't exist."""
    SQLModel.metadata.create_all(engine)
    missing = missing_columns(engine)
    if missing:
        # create_all never alters existing tables; an older database needs its migrations applied.
        logger.error("Database schema is out of date (missing columns: %s). "
                     "Run: python -m alembic -c backend/alembic/alembic.ini upgrade head",
                     ", ".join(missing))


def missing_columns(bind) -> list:
    """Model columns that are absent from existing database tables."""
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    missing = []
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {c["name"] for c in inspector.get_columns(table.name)}
        missing += [f"{table.name}.{c.name}" for c in table.columns if c.name not in present]
    return missing

from typing import Generator

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
