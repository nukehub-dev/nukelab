"""add plan availability flags

Revision ID: a3b8c1d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-11-28 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a3b8c1d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None

PLAN_TABLE = "server_plans"
COLUMNS = (
    sa.Column("allow_servers", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("allow_batch_jobs", sa.Boolean(), nullable=False, server_default=sa.false()),
)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # AUTO_CREATE_TABLES may have created the current model before Alembic runs.
    if PLAN_TABLE not in _tables():
        return
    existing = _columns(PLAN_TABLE)
    added_jobs = False
    for column in COLUMNS:
        if column.name not in existing:
            op.add_column(PLAN_TABLE, column)
            added_jobs = added_jobs or column.name == "allow_batch_jobs"

    # Existing plans were all job-eligible before this flag. Preserve that
    # behavior once; new plans created through the API default to opt-in.
    if added_jobs or "allow_batch_jobs" in _columns(PLAN_TABLE):
        op.execute(
            sa.text(
                f"UPDATE {PLAN_TABLE} SET allow_batch_jobs = true "
                "WHERE allow_batch_jobs = false "
                "AND (gpu_limit = 0 OR gpu_limit IS NULL)"
            )
        )


def downgrade() -> None:
    if PLAN_TABLE not in _tables():
        return
    existing = _columns(PLAN_TABLE)
    for column in reversed(COLUMNS):
        if column.name in existing:
            op.drop_column(PLAN_TABLE, column.name)
