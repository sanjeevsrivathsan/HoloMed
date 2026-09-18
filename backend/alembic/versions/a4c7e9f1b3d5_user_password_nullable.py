"""user.hashed_password nullable (Google-only accounts)

Revision ID: a4c7e9f1b3d5
Revises: 9d5e3f7a2b81
Create Date: 2026-09-18

The User model declares hashed_password Optional and Google sign-in creates accounts without a
password (hashed_password=None), but c3f9a1d2e4b6 created the column NOT NULL. Upgrade only relaxes
the constraint: type, indexes, defaults and existing values are unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a4c7e9f1b3d5'
down_revision: Union[str, None] = '9d5e3f7a2b81'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('user') as batch_op:  # SQLite cannot ALTER COLUMN in place
        batch_op.alter_column('hashed_password', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # NOT NULL cannot be restored while password-less (Google-only) accounts exist, and inventing a
    # value for them would change their data. Stop instead; the operator decides what to do with them.
    users = sa.table('user', sa.column('hashed_password', sa.String()))
    missing = op.get_bind().execute(
        sa.select(sa.func.count()).select_from(users).where(users.c.hashed_password.is_(None))).scalar()
    if missing:
        raise RuntimeError(
            f"Cannot downgrade a4c7e9f1b3d5: {missing} user(s) have no password (hashed_password is NULL, "
            "e.g. Google-only accounts). Resolve them first; no data was changed.")
    with op.batch_alter_table('user') as batch_op:
        batch_op.alter_column('hashed_password', existing_type=sa.String(), nullable=False)
