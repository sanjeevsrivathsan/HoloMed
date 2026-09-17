"""Record the processing stage of a report extraction (Phase 7A-B)

Revision ID: 7a2b3c4d5e60
Revises: 7a1c2e3d4f50
Create Date: 2026-09-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '7a2b3c4d5e60'
down_revision: Union[str, None] = '7a1c2e3d4f50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('reportextraction') as batch_op:
        batch_op.add_column(sa.Column('stage', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('reportextraction') as batch_op:
        batch_op.drop_column('stage')
