"""add batch job admission reservations and job writer exclusion

Revision ID: e2c7a9f4d6b1
Revises: b7d4e1c9a2f5
Create Date: 2026-11-27 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "e2c7a9f4d6b1"
down_revision = "b7d4e1c9a2f5"
branch_labels = None
depends_on = None

JOB_TABLE = "batch_jobs"
VOLUME_OPERATION_TABLE = "volume_operations"
EXCLUSIVE_INDEX = "uq_volume_operations_exclusive"
RESERVED_JOB_STATES = "('reserved', 'running', 'recovery_required')"

JOB_COLUMNS = (
    sa.Column("reserved_cpu", sa.Float(), nullable=True),
    sa.Column("reserved_memory_mib", sa.Integer(), nullable=True),
    sa.Column("reserved_disk_mib", sa.Integer(), nullable=True),
    sa.Column("volume_fencing_token", sa.UUID(), nullable=True),
    sa.Column(
        "cleanup_state",
        sa.String(length=20),
        nullable=False,
        server_default="pending",
    ),
    sa.Column(
        "cleanup_attempts",
        sa.Integer(),
        nullable=False,
        server_default="0",
    ),
    sa.Column("last_cleanup_at", sa.DateTime(), nullable=True),
)


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _exclusive_predicate(*, include_job_writer: bool) -> str:
    kinds = "'backup', 'restore', 'job_writer'" if include_job_writer else "'backup', 'restore'"
    return f"kind IN ({kinds}) AND state IN {RESERVED_JOB_STATES}"


def _replace_exclusive_index(*, include_job_writer: bool) -> None:
    if EXCLUSIVE_INDEX in _indexes(VOLUME_OPERATION_TABLE):
        op.drop_index(EXCLUSIVE_INDEX, table_name=VOLUME_OPERATION_TABLE)
    op.create_index(
        EXCLUSIVE_INDEX,
        VOLUME_OPERATION_TABLE,
        ["volume_id"],
        unique=True,
        postgresql_where=sa.text(_exclusive_predicate(include_job_writer=include_job_writer)),
    )


def upgrade() -> None:
    # AUTO_CREATE_TABLES may have created current models before Alembic runs.
    existing = _columns(JOB_TABLE)
    for column in JOB_COLUMNS:
        if column.name not in existing:
            op.add_column(JOB_TABLE, column)
    _replace_exclusive_index(include_job_writer=True)


def downgrade() -> None:
    existing = _columns(JOB_TABLE)
    for column in reversed(JOB_COLUMNS):
        if column.name in existing:
            op.drop_column(JOB_TABLE, column.name)
    _replace_exclusive_index(include_job_writer=False)
