"""Report date provenance and extracted date candidates (Phase 7B)

Revision ID: 7b1a2c3d4e50
Revises: 7a2b3c4d5e60
Create Date: 2026-09-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '7b1a2c3d4e50'
down_revision: Union[str, None] = '7a2b3c4d5e60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('report') as batch_op:
        batch_op.add_column(sa.Column('date_source', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('date_confirmed', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('detected_date', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table('reportextraction') as batch_op:
        batch_op.add_column(sa.Column('date_candidates', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('reportextraction') as batch_op:
        batch_op.drop_column('date_candidates')
    with op.batch_alter_table('report') as batch_op:
        batch_op.drop_column('detected_date')
        batch_op.drop_column('date_confirmed')
        batch_op.drop_column('date_source')
