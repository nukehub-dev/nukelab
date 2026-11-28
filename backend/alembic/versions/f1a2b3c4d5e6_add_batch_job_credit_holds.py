"""add batch job credit holds and billing journal

Revision ID: f1a2b3c4d5e6
Revises: e2c7a9f4d6b1
Create Date: 2026-11-28 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "e2c7a9f4d6b1"
branch_labels = None
depends_on = None

JOB_TABLE = "batch_jobs"
HOLD_TABLE = "credit_holds"
USER_HOLD_INDEX = "ix_credit_holds_user_state"
JOB_HOLD_INDEX = "uq_credit_holds_job_id"

JOB_COLUMNS = (
    sa.Column("authorized_credits", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("billing_rate_per_hour", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("billing_state", sa.String(length=20), nullable=False, server_default="none"),
)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_credit_holds() -> None:
    op.create_table(
        HOLD_TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="held"),
        sa.Column("charged_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unpaid_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["batch_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(USER_HOLD_INDEX, HOLD_TABLE, ["user_id", "state"], unique=False)
    op.create_index(JOB_HOLD_INDEX, HOLD_TABLE, ["job_id"], unique=True)


def upgrade() -> None:
    # AUTO_CREATE_TABLES may have created current models before Alembic runs.
    tables = _tables()
    if JOB_TABLE in tables:
        existing = _columns(JOB_TABLE)
        for column in JOB_COLUMNS:
            if column.name not in existing:
                op.add_column(JOB_TABLE, column)
    if HOLD_TABLE not in tables:
        _create_credit_holds()
    else:
        existing = _columns(HOLD_TABLE)
        if "unpaid_credits" not in existing:
            op.add_column(
                HOLD_TABLE,
                sa.Column(
                    "unpaid_credits",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                ),
            )
        indexes = _indexes(HOLD_TABLE)
        if USER_HOLD_INDEX not in indexes:
            op.create_index(USER_HOLD_INDEX, HOLD_TABLE, ["user_id", "state"], unique=False)
        if JOB_HOLD_INDEX not in indexes:
            op.create_index(JOB_HOLD_INDEX, HOLD_TABLE, ["job_id"], unique=True)


def downgrade() -> None:
    if HOLD_TABLE in _tables():
        op.drop_table(HOLD_TABLE)
    if JOB_TABLE in _tables():
        existing = _columns(JOB_TABLE)
        for column in reversed(JOB_COLUMNS):
            if column.name in existing:
                op.drop_column(JOB_TABLE, column.name)
