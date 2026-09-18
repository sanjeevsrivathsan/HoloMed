"""add_user_auth_fields

Revision ID: c3f9a1d2e4b6
Revises: b241ba6d1b75
Create Date: 2026-08-23 09:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "c3f9a1d2e4b6"
down_revision = "b241ba6d1b75"
branch_labels = None
depends_on = None

def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns

def upgrade() -> None:
    # Add hashed_password if missing
    if not _column_exists("user", "hashed_password"):
        op.add_column(
            "user",
            sa.Column("hashed_password", sa.String(), nullable=False, server_default=""),
        )
        # Remove default after population
        with op.batch_alter_table("user") as batch_op:  # SQLite cannot ALTER COLUMN in place
            batch_op.alter_column("hashed_password", server_default=None)
    # Add is_active if missing
    if not _column_exists("user", "is_active"):
        op.add_column(
            "user",
            # sa.true() renders per dialect: true on PostgreSQL, 1 on SQLite (a literal 1 is an
            # integer, which PostgreSQL rejects as a boolean default).
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        with op.batch_alter_table("user") as batch_op:  # SQLite cannot ALTER COLUMN in place
            batch_op.alter_column("is_active", server_default=None)

def downgrade() -> None:
    if _column_exists("user", "is_active"):
        op.drop_column("user", "is_active")
    if _column_exists("user", "hashed_password"):
        op.drop_column("user", "hashed_password")
