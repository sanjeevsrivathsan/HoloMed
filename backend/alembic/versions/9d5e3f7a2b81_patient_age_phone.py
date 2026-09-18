"""Patient age and phone number

Revision ID: 9d5e3f7a2b81
Revises: 8c4d2e6f1a70
Create Date: 2026-09-18

Additive: two nullable columns; existing rows (and date_of_birth) are left unchanged.
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '9d5e3f7a2b81'
down_revision: Union[str, None] = '8c4d2e6f1a70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns('patient')}
    with op.batch_alter_table('patient') as batch_op:
        if 'age' not in present:
            batch_op.add_column(sa.Column('age', sa.Integer(), nullable=True))
        if 'phone' not in present:
            batch_op.add_column(sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('patient') as batch_op:
        batch_op.drop_column('phone')
        batch_op.drop_column('age')
