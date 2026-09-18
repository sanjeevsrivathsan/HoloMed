"""Patient workspace: patient identity, patient-owned AI analyses, patient-scoped audit

Revision ID: 8c4d2e6f1a70
Revises: 7b1a2c3d4e50
Create Date: 2026-09-18

Additive and data-preserving: new columns are nullable so older builds keep working, every
existing patient is backfilled with a UUID and a per-user code (HML-000001, ...), and any
report without a patient is attached to its owner's first patient.
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '8c4d2e6f1a70'
down_revision: Union[str, None] = '7b1a2c3d4e50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STR = sqlmodel.sql.sqltypes.AutoString


def _backfill_patients(conn) -> None:
    now = datetime.utcnow()
    rows = conn.execute(sa.text("SELECT id, owner_id FROM patient WHERE uid IS NULL OR patient_code IS NULL "
                                "ORDER BY owner_id, id")).fetchall()
    per_owner = {}
    for patient_id, owner_id in rows:
        per_owner[owner_id] = per_owner.get(owner_id, 0) + 1
        conn.execute(sa.text("UPDATE patient SET uid = :uid, patient_code = :code, created_at = :now, "
                             "updated_at = :now WHERE id = :id"),
                     {"uid": str(uuid.uuid4()), "code": f"HML-{per_owner[owner_id]:06d}", "now": now, "id": patient_id})

    orphan_owners = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT owner_id FROM report WHERE patient_id IS NULL")).fetchall()]
    for owner_id in orphan_owners:
        first = conn.execute(sa.text("SELECT id FROM patient WHERE owner_id = :o ORDER BY id LIMIT 1"),
                             {"o": owner_id}).scalar()
        if first is None:
            conn.execute(sa.text("INSERT INTO patient (owner_id, display_name, uid, patient_code, created_at, updated_at) "
                                 "VALUES (:o, 'Patient 1', :uid, 'HML-000001', :now, :now)"),
                         {"o": owner_id, "uid": str(uuid.uuid4()), "now": now})
            first = conn.execute(sa.text("SELECT id FROM patient WHERE owner_id = :o ORDER BY id LIMIT 1"),
                                 {"o": owner_id}).scalar()
        conn.execute(sa.text("UPDATE report SET patient_id = :p WHERE owner_id = :o AND patient_id IS NULL"),
                     {"p": first, "o": owner_id})


def _columns(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    # Idempotent: SQLite DDL is not transactional, and a newer build's startup (create_all) may already
    # have created ai_analysis. Each step only adds what is missing.
    present = _columns('patient')
    new_columns = [sa.Column('uid', _STR(), nullable=True), sa.Column('patient_code', _STR(), nullable=True),
                   sa.Column('date_of_birth', _STR(), nullable=True), sa.Column('sex', _STR(), nullable=True),
                   sa.Column('created_at', sa.DateTime(), nullable=True), sa.Column('updated_at', sa.DateTime(), nullable=True)]
    with op.batch_alter_table('patient') as batch_op:
        for column in new_columns:
            if column.name not in present:
                batch_op.add_column(column)

    _backfill_patients(op.get_bind())

    if 'ix_patient_uid' not in _indexes('patient'):
        with op.batch_alter_table('patient') as batch_op:
            batch_op.create_index('ix_patient_uid', ['uid'], unique=True)
            batch_op.create_index('ix_patient_patient_code', ['patient_code'], unique=False)
            batch_op.create_unique_constraint('uq_patient_owner_code', ['owner_id', 'patient_code'])

    if 'patient_id' not in _columns('auditlog'):
        with op.batch_alter_table('auditlog') as batch_op:
            batch_op.add_column(sa.Column('patient_id', sa.Integer(), nullable=True))
            batch_op.create_index('ix_auditlog_patient_id', ['patient_id'], unique=False)
            batch_op.create_foreign_key('fk_auditlog_patient_id', 'patient', ['patient_id'], ['id'])

    for table in ('study', 'report'):
        if f'ix_{table}_patient_id' not in _indexes(table):
            with op.batch_alter_table(table) as batch_op:
                batch_op.create_index(f'ix_{table}_patient_id', ['patient_id'], unique=False)

    if 'ai_analysis' in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        'ai_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uid', _STR(), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('patient_id', sa.Integer(), nullable=False),
        sa.Column('study_id', sa.Integer(), nullable=True),
        sa.Column('instance_id', sa.Integer(), nullable=True),
        sa.Column('input_format', _STR(), nullable=False),
        sa.Column('input_sha256', _STR(), nullable=False),
        sa.Column('provider', _STR(), nullable=False),
        sa.Column('model_name', _STR(), nullable=False),
        sa.Column('model_weights', _STR(), nullable=False),
        sa.Column('weight_sha256', _STR(), nullable=False),
        sa.Column('primary_pathology', _STR(), nullable=False),
        sa.Column('primary_score', sa.Float(), nullable=False),
        sa.Column('selected_target', _STR(), nullable=True),
        sa.Column('response_json', _STR(), nullable=False),
        sa.Column('text_explanations_json', _STR(), nullable=False, server_default='{}'),
        sa.Column('result_id', _STR(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['owner_id'], ['user.id']),
        sa.ForeignKeyConstraint(['patient_id'], ['patient.id']),
        sa.ForeignKeyConstraint(['study_id'], ['study.id']),
        sa.ForeignKeyConstraint(['instance_id'], ['instance.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_analysis_uid', 'ai_analysis', ['uid'], unique=True)
    op.create_index('ix_ai_analysis_owner_id', 'ai_analysis', ['owner_id'], unique=False)
    op.create_index('ix_ai_analysis_patient_id', 'ai_analysis', ['patient_id'], unique=False)
    op.create_index('ix_ai_analysis_study_id', 'ai_analysis', ['study_id'], unique=False)
    op.create_index('ix_ai_analysis_result_id', 'ai_analysis', ['result_id'], unique=False)


def downgrade() -> None:
    op.drop_table('ai_analysis')
    with op.batch_alter_table('report') as batch_op:
        batch_op.drop_index('ix_report_patient_id')
    with op.batch_alter_table('study') as batch_op:
        batch_op.drop_index('ix_study_patient_id')
    with op.batch_alter_table('auditlog') as batch_op:
        batch_op.drop_constraint('fk_auditlog_patient_id', type_='foreignkey')
        batch_op.drop_index('ix_auditlog_patient_id')
        batch_op.drop_column('patient_id')
    with op.batch_alter_table('patient') as batch_op:
        batch_op.drop_constraint('uq_patient_owner_code', type_='unique')
        batch_op.drop_index('ix_patient_patient_code')
        batch_op.drop_index('ix_patient_uid')
        for column in ('updated_at', 'created_at', 'sex', 'date_of_birth', 'patient_code', 'uid'):
            batch_op.drop_column(column)
