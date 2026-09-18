import logging
import os
from typing import Mapping, Optional
from sqlalchemy import inspect
from sqlalchemy.engine import Engine, make_url
from sqlmodel import SQLModel, create_engine, Session

from . import config

logger = logging.getLogger(__name__)


def resolve_database_url(env: Optional[Mapping[str, str]] = None, configured: Optional[str] = None) -> str:
    """The database the backend uses.

    DATABASE_URL (backend.config; e.g. PostgreSQL on Supabase in production) is the database, with
    SQLite at ./data/holomed.db when it is unset. HOLUMED_DB_PATH, when set, is an explicit local
    override to a SQLite file (tests point it at a throwaway database); it wins and is logged.
    """
    env = os.environ if env is None else env
    url = configured if configured is not None else config.DATABASE_URL
    override = env.get("HOLUMED_DB_PATH")
    if override:
        if env.get("DATABASE_URL"):
            logger.warning("HOLUMED_DB_PATH is set: using that SQLite file instead of DATABASE_URL")
        return f"sqlite:///{override}"
    # Hosted providers often hand out postgres://, which SQLAlchemy only accepts as postgresql://.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def build_engine(url: str) -> Engine:
    """SQLite keeps its previous engine settings (SQLAlchemy already sets check_same_thread=False for
    file databases); server databases check pooled connections before use."""
    if make_url(url).get_backend_name() == "sqlite":
        return create_engine(url, echo=False)
    return create_engine(url, echo=False, pool_pre_ping=True)


DATABASE_URL = resolve_database_url()
engine = build_engine(DATABASE_URL)
# Backend and driver only; the URL itself can carry credentials and is never logged.
logger.info("Database: %s (%s)", engine.dialect.name, engine.dialect.driver)

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
