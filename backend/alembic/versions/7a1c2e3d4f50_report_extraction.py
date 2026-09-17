"""Report extraction and measurement review tables (Phase 7A)

Revision ID: 7a1c2e3d4f50
Revises: 238f5e098b3e
Create Date: 2026-09-17 13:00:00

Adds derived-artifact tables only; existing tables are unchanged.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '7a1c2e3d4f50'
down_revision: Union[str, None] = '238f5e098b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_str = sqlmodel.sql.sqltypes.AutoString


def upgrade() -> None:
    op.create_table(
        'reportextraction',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('status', _str(), nullable=False),
        sa.Column('method', _str(), nullable=False),
        sa.Column('quality', _str(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('text', _str(), nullable=False),
        sa.Column('document_date', _str(), nullable=True),
        sa.Column('error_code', _str(), nullable=True),
        sa.Column('warnings', _str(), nullable=False),
        sa.Column('timings', _str(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.ForeignKeyConstraint(['report_id'], ['report.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reportextraction_owner_id'), 'reportextraction', ['owner_id'], unique=False)
    op.create_index(op.f('ix_reportextraction_report_id'), 'reportextraction', ['report_id'], unique=True)
    op.create_table(
        'extractedmeasurement',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('test_name', _str(), nullable=False),
        sa.Column('source_name', _str(), nullable=False),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('value_text', _str(), nullable=False),
        sa.Column('unit', _str(), nullable=False),
        sa.Column('reference_range', _str(), nullable=True),
        sa.Column('flag', _str(), nullable=False),
        sa.Column('confidence', _str(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('line_text', _str(), nullable=False),
        sa.Column('review_status', _str(), nullable=False),
        sa.Column('edited', sa.Boolean(), nullable=False),
        sa.Column('measurement_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['measurement_id'], ['medicalmeasurement.id']),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.ForeignKeyConstraint(['report_id'], ['report.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_extractedmeasurement_owner_id'), 'extractedmeasurement', ['owner_id'], unique=False)
    op.create_index(op.f('ix_extractedmeasurement_report_id'), 'extractedmeasurement', ['report_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_extractedmeasurement_report_id'), table_name='extractedmeasurement')
    op.drop_index(op.f('ix_extractedmeasurement_owner_id'), table_name='extractedmeasurement')
    op.drop_table('extractedmeasurement')
    op.drop_index(op.f('ix_reportextraction_report_id'), table_name='reportextraction')
    op.drop_index(op.f('ix_reportextraction_owner_id'), table_name='reportextraction')
    op.drop_table('reportextraction')
