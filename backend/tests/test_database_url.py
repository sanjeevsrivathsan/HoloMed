"""The backend engine follows DATABASE_URL (PostgreSQL in production), with SQLite as the local default.

No test connects to a database: PostgreSQL engines are only built, never used."""
import json
import os
import subprocess
import sys
from pathlib import Path

from backend import database
from backend.database import build_engine, resolve_database_url

ROOT = Path(__file__).resolve().parents[2]
PG = "postgresql://holomed_user:s3cret-pw@db.example.supabase.co:5432/postgres"


def test_sqlite_database_url_creates_a_sqlite_engine(tmp_path):
    url = resolve_database_url(env={}, configured=f"sqlite:///{tmp_path / 'local.db'}")
    engine = build_engine(url)
    assert engine.dialect.name == "sqlite"
    assert engine.url.database == str(tmp_path / "local.db")
    engine.dispose()


def test_default_is_the_local_sqlite_file():
    assert resolve_database_url(env={}, configured="sqlite:///./data/holomed.db") == "sqlite:///./data/holomed.db"


def test_postgresql_database_url_creates_a_postgresql_engine_without_connecting():
    engine = build_engine(resolve_database_url(env={"DATABASE_URL": PG}, configured=PG))
    assert (engine.dialect.name, engine.dialect.driver) == ("postgresql", "psycopg2")
    assert engine.url.host == "db.example.supabase.co" and engine.url.database == "postgres"
    assert engine.pool._pre_ping is True
    assert "s3cret-pw" not in str(engine.url) and "s3cret-pw" not in repr(engine)   # never rendered in logs
    engine.dispose()


def test_postgres_scheme_is_accepted():
    url = resolve_database_url(env={}, configured="postgres://u:p@host:6543/postgres")
    assert url == "postgresql://u:p@host:6543/postgres"
    assert build_engine(url).dialect.name == "postgresql"


def test_holumed_db_path_is_an_explicit_sqlite_override_and_is_logged(caplog):
    with caplog.at_level("WARNING", logger="backend.database"):
        url = resolve_database_url(env={"HOLUMED_DB_PATH": "/tmp/throwaway.db", "DATABASE_URL": PG}, configured=PG)
    assert url == "sqlite:///" + "/tmp/throwaway.db"
    assert "HOLUMED_DB_PATH" in caplog.text and "s3cret-pw" not in caplog.text and "supabase" not in caplog.text


def test_the_backend_engine_uses_the_configured_database_url():
    """Import the real modules with DATABASE_URL set (as in production): the engine must not fall back
    to SQLite, and the credentials must not be logged."""
    env = {k: v for k, v in os.environ.items() if k not in ("HOLUMED_DB_PATH", "DATABASE_URL")}
    env.update(DATABASE_URL=PG, JWT_SECRET="x")
    code = ("import json, logging, io; s = io.StringIO(); logging.basicConfig(stream=s, level=logging.INFO)\n"
            "from backend import config, database\n"
            "print(json.dumps({'config': config.DATABASE_URL, 'dialect': database.engine.dialect.name,"
            " 'host': database.engine.url.host, 'log': s.getvalue()}))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["config"] == PG
    assert result["dialect"] == "postgresql" and result["host"] == "db.example.supabase.co"
    assert "Database: postgresql (psycopg2)" in result["log"] and "s3cret-pw" not in result["log"]


def test_alembic_uses_the_shared_engine():
    env_py = (ROOT / "backend" / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "from backend.database import engine" in env_py
    assert "engine.connect()" in env_py and "engine_from_config(" not in env_py.split("def run_migrations_online")[1]


def test_this_test_run_uses_the_resolved_url():
    assert str(database.engine.url) == str(build_engine(database.DATABASE_URL).url)
