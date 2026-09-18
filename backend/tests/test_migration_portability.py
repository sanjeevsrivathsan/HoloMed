"""Migration c3f9a1d2e4b6 (user auth fields) on SQLite and PostgreSQL.

PostgreSQL rejected the original `is_active BOOLEAN DEFAULT 1` (an integer default on a boolean);
the migration now uses sa.true(), rendered per dialect.

The PostgreSQL tests are opt-in: set HOLOMED_TEST_POSTGRES_URL to a disposable local server. They work
inside a uniquely named schema that is dropped afterwards, only on localhost, and never on DATABASE_URL.
"""
import contextlib
import importlib.util
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateColumn

from backend import database

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "c3f9a1d2e4b6_add_user_auth_fields.py"
PG_URL = os.getenv("HOLOMED_TEST_POSTGRES_URL", "")


def _load_migration():
    spec = importlib.util.spec_from_file_location("c3f9a1d2e4b6_under_test", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingOp:
    """Stands in for alembic.op to capture what the migration asks for."""

    def __init__(self):
        self.added, self.altered = [], []

    def add_column(self, table, column):
        self.added.append((table, column))

    @contextlib.contextmanager
    def batch_alter_table(self, table):
        op = self

        class Batch:
            def alter_column(self, name, **kw):
                op.altered.append((table, name, kw))
        yield Batch()


def test_auth_fields_defaults_render_portably(monkeypatch):
    migration = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)
    monkeypatch.setattr(migration, "_column_exists", lambda table, column: False)
    migration.upgrade()
    columns = {c.name: c for _, c in recorder.added}
    assert set(columns) == {"hashed_password", "is_active"}
    ddl = {name: {d: str(CreateColumn(col).compile(dialect=dialect)) for d, dialect in
                  (("pg", postgresql.dialect()), ("sqlite", sqlite.dialect()))} for name, col in columns.items()}
    assert ddl["is_active"]["pg"] == "is_active BOOLEAN DEFAULT true NOT NULL"
    assert ddl["is_active"]["sqlite"] == "is_active BOOLEAN DEFAULT (1) NOT NULL"   # SQLite: integer 1, as before
    assert ddl["hashed_password"]["pg"] == "hashed_password VARCHAR DEFAULT '' NOT NULL"
    assert ddl["hashed_password"]["sqlite"] == "hashed_password VARCHAR DEFAULT '' NOT NULL"
    # the defaults only fill existing rows and are removed again, as before
    assert [(t, n, kw) for t, n, kw in recorder.altered] == [
        ("user", "hashed_password", {"server_default": None}), ("user", "is_active", {"server_default": None})]


def _config():
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


def _upgrade_with_existing_user(engine, monkeypatch):
    from alembic import command
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(_config(), "b241ba6d1b75")
    assert "is_active" not in {c["name"] for c in inspect(engine).get_columns("user")}
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO \"user\" (email, created_at) VALUES ('existing@example.com', '2026-01-01')"))
    command.upgrade(_config(), "c3f9a1d2e4b6")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT is_active, hashed_password FROM \"user\"")).one()
    columns = {c["name"]: c for c in inspect(engine).get_columns("user")}
    return row, columns


def test_auth_fields_migration_on_sqlite(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    row, columns = _upgrade_with_existing_user(engine, monkeypatch)
    assert tuple(row) == (1, "")                                   # existing users are active
    assert columns["is_active"]["default"] is None and columns["is_active"]["nullable"] is False
    assert columns["hashed_password"]["default"] is None
    engine.dispose()


def _local_pg():
    if not PG_URL:
        pytest.skip("HOLOMED_TEST_POSTGRES_URL not set (disposable local PostgreSQL)")
    if PG_URL == os.getenv("DATABASE_URL") or urlparse(PG_URL).hostname not in ("localhost", "127.0.0.1", "::1"):
        pytest.skip("HOLOMED_TEST_POSTGRES_URL must be a local, disposable server (never DATABASE_URL)")


@pytest.fixture
def pg_schema_engine():
    _local_pg()
    schema = f"holomed_migration_test_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(PG_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_auth_fields_migration_on_postgresql(pg_schema_engine, monkeypatch):
    row, columns = _upgrade_with_existing_user(pg_schema_engine, monkeypatch)
    assert tuple(row) == (True, "")
    assert isinstance(columns["is_active"]["type"], sa.Boolean)
    assert columns["is_active"]["default"] is None and columns["is_active"]["nullable"] is False
    assert columns["hashed_password"]["default"] is None
    from alembic import command
    command.downgrade(_config(), "b241ba6d1b75")
    assert not {"is_active", "hashed_password"} & {c["name"] for c in inspect(pg_schema_engine).get_columns("user")}


# ── Complete history on a fresh database ──────────────────────────────────────
# Tables that only the app's create_all() used to create; 238f5e098b3e now creates them.
PHASE8_TABLES = {"consentrecord", "medicalmeasurement", "reportsummary", "storageconnection", "template"}


def _head() -> str:
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(_config()).get_current_head()


def _table_shape(engine, table):
    insp = inspect(engine)
    columns = sorted((c["name"], c["type"].compile(dialect=engine.dialect), c["nullable"], c["default"])
                     for c in insp.get_columns(table))
    fks = sorted((tuple(f["constrained_columns"]), f["referred_table"], tuple(f["referred_columns"]),
                  tuple(sorted((f.get("options") or {}).items()))) for f in insp.get_foreign_keys(table))
    indexes = sorted((tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(table))
    uniques = sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints(table))
    return columns, fks, indexes, uniques, insp.get_pk_constraint(table)["constrained_columns"]


def _assert_complete_history(engine, reference_engine, monkeypatch):
    """Migrate a fresh database to head and compare the Phase 8 tables with create_all()."""
    from alembic import command
    from sqlmodel import SQLModel
    import backend.models  # noqa: F401  (registers every model)
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(_config(), "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == _head()
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert PHASE8_TABLES <= tables
    assert set(SQLModel.metadata.tables) <= tables          # the history alone creates every model table
    # every foreign key in the migrated schema resolves to an existing table and column
    for table in tables:
        for fk in insp.get_foreign_keys(table):
            assert fk["referred_table"] in tables, (table, fk)
            referred = {c["name"] for c in insp.get_columns(fk["referred_table"])}
            assert set(fk["referred_columns"]) <= referred, (table, fk)
    assert database.missing_columns(engine) == []
    # the migrated Phase 8 tables are exactly what the models define
    SQLModel.metadata.create_all(reference_engine, tables=[SQLModel.metadata.tables[t] for t in
                                                           ("user", "patient", "report", *sorted(PHASE8_TABLES))])
    for table in sorted(PHASE8_TABLES):
        assert _table_shape(engine, table) == _table_shape(reference_engine, table), table


def test_complete_history_on_fresh_sqlite(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    reference = create_engine(f"sqlite:///{tmp_path / 'models.db'}")
    _assert_complete_history(engine, reference, monkeypatch)
    engine.dispose()
    reference.dispose()


def test_phase8_tables_already_created_by_startup_are_kept(tmp_path, monkeypatch):
    """A development database whose startup create_all() made these tables still upgrades."""
    from alembic import command
    from sqlmodel import SQLModel
    import backend.models  # noqa: F401
    engine = create_engine(f"sqlite:///{tmp_path / 'dev.db'}")
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(_config(), "fdde5eb0c094")
    SQLModel.metadata.create_all(engine, tables=[SQLModel.metadata.tables[t] for t in sorted(PHASE8_TABLES)])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO \"user\" (id, email, hashed_password, is_active, created_at) "
                          "VALUES (1, 'dev@example.com', '', 1, '2026-01-01')"))
        conn.execute(text("INSERT INTO template (id, owner_id, name, category, description, sections, updated_at) "
                          "VALUES (1, 1, 'CBC', 'Lab', 'kept', '[]', '2026-01-01')"))
    command.upgrade(_config(), "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT description FROM template WHERE id = 1")).scalar() == "kept"
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == _head()
    engine.dispose()


@pytest.fixture
def pg_reference_engine():
    _local_pg()
    schema = f"holomed_models_ref_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(PG_URL, connect_args={"options": f"-csearch_path={schema}"})
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_complete_history_on_fresh_postgresql(pg_schema_engine, pg_reference_engine, monkeypatch):
    _assert_complete_history(pg_schema_engine, pg_reference_engine, monkeypatch)


# ── a4c7e9f1b3d5: user.hashed_password nullable (Google-only accounts) ───────
PASSWORD_NULLABLE = "a4c7e9f1b3d5"


def _user_constraints(engine):
    insp = inspect(engine)
    columns = {c["name"]: (c["type"].compile(dialect=engine.dialect), c["nullable"], c["default"])
               for c in insp.get_columns("user")}
    indexes = sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes("user"))
    uniques = sorted(tuple(u["column_names"]) for u in insp.get_unique_constraints("user"))
    return columns, indexes, uniques


def _version(engine):
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def _assert_password_nullable_migration(engine, monkeypatch):
    from alembic import command
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(_config(), "9d5e3f7a2b81")
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO "user" (id, email, hashed_password, is_active, created_at) '
                          "VALUES (1, 'password@example.com', 'hash-1', :active, '2026-01-01 00:00:00')"),
                     {"active": True})
    before_columns, before_indexes, before_uniques = _user_constraints(engine)
    assert before_columns["hashed_password"][1] is False

    command.upgrade(_config(), "head")
    assert _head() == PASSWORD_NULLABLE and _version(engine) == PASSWORD_NULLABLE
    columns, indexes, uniques = _user_constraints(engine)
    assert columns["hashed_password"] == (before_columns["hashed_password"][0], True, None)   # type/default kept
    assert {k: v for k, v in columns.items() if k != "hashed_password"} == \
        {k: v for k, v in before_columns.items() if k != "hashed_password"}
    assert (indexes, uniques) == (before_indexes, before_uniques)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT hashed_password FROM "user" WHERE id = 1')).scalar() == "hash-1"
        conn.execute(text('INSERT INTO "user" (id, email, hashed_password, is_active, created_at, google_id) '
                          "VALUES (2, 'google@example.com', NULL, :active, '2026-01-01 00:00:00', 'google-sub-2')"),
                     {"active": True})

    # Downgrade refuses while a password-less account exists, and changes nothing.
    with pytest.raises(RuntimeError, match="1 user\\(s\\) have no password"):
        command.downgrade(_config(), "9d5e3f7a2b81")
    assert _version(engine) == PASSWORD_NULLABLE and _user_constraints(engine)[0]["hashed_password"][1] is True
    with engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM "user"')).scalar() == 2

    # Without such accounts it restores NOT NULL and keeps the password users.
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM "user" WHERE id = 2'))
    command.downgrade(_config(), "9d5e3f7a2b81")
    assert _version(engine) == "9d5e3f7a2b81"
    columns, indexes, uniques = _user_constraints(engine)
    assert columns == before_columns and (indexes, uniques) == (before_indexes, before_uniques)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT hashed_password FROM "user" WHERE id = 1')).scalar() == "hash-1"


def test_password_nullable_migration_on_sqlite(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'users.db'}")
    _assert_password_nullable_migration(engine, monkeypatch)
    engine.dispose()


def test_password_nullable_migration_on_postgresql(pg_schema_engine, monkeypatch):
    _assert_password_nullable_migration(pg_schema_engine, monkeypatch)


def test_migrated_user_table_matches_the_model(tmp_path, monkeypatch):
    """After the complete history, user.hashed_password is nullable as the model (and Google sign-in) expect."""
    from alembic import command
    from backend.models import User
    engine = create_engine(f"sqlite:///{tmp_path / 'head.db'}")
    monkeypatch.setattr(database, "engine", engine)
    command.upgrade(_config(), "head")
    columns = {c["name"]: c["nullable"] for c in inspect(engine).get_columns("user")}
    assert columns == {c.name: c.nullable for c in User.__table__.columns}
    engine.dispose()
