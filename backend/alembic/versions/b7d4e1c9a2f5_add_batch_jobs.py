"""add single-run batch jobs and bounded log payloads

Revision ID: b7d4e1c9a2f5
Revises: a4c9e2f7b1d3
Create Date: 2026-11-27 00:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7d4e1c9a2f5"
down_revision = "a4c9e2f7b1d3"
branch_labels = None
depends_on = None

JOB_TABLE = "batch_jobs"
LOG_TABLE = "batch_job_logs"

JOB_INDEXES = (
    (
        "uq_batch_jobs_owner_idempotency",
        ["user_id", "idempotency_key_hash"],
        True,
        None,
    ),
    ("ix_batch_jobs_owner_history", ["user_id", "created_at", "id"], False, None),
    (
        "ix_batch_jobs_pending_dispatch",
        ["created_at", "id"],
        False,
        "state = 'queued'",
    ),
    (
        "ix_batch_jobs_queued_expiry",
        ["queue_expires_at", "id"],
        False,
        "state = 'queued'",
    ),
    (
        "ix_batch_jobs_active_recovery",
        ["state", "heartbeat_at", "id"],
        False,
        "state IN ('starting', 'running', 'cancelling', 'recovery_required')",
    ),
    (
        "ix_batch_jobs_unreleased_reservations",
        ["reserved_at", "id"],
        False,
        "reservation_active = true",
    ),
)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _create_index(name, table, columns, unique, where):
    if name in _indexes(table):
        return
    op.create_index(
        name,
        table,
        columns,
        unique=unique,
        postgresql_where=sa.text(where) if where is not None else None,
    )


def _create_jobs() -> None:
    op.create_table(
        JOB_TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("plan_id", sa.UUID(), nullable=True),
        sa.Column("volume_id", sa.UUID(), nullable=True),
        sa.Column("argv", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_runtime_seconds", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(), nullable=False),
        sa.Column("queue_expires_at", sa.DateTime(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(), nullable=True),
        sa.Column("create_requested_at", sa.DateTime(), nullable=True),
        sa.Column("start_requested_at", sa.DateTime(), nullable=True),
        sa.Column("start_observed_at", sa.DateTime(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(), nullable=True),
        sa.Column(
            "revision_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "plan_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "volume_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "reservation_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("volume_operation_id", sa.UUID(), nullable=True),
        sa.Column("container_id", sa.String(length=255), nullable=True),
        sa.Column("container_name", sa.String(length=255), nullable=True),
        sa.Column(
            "runtime_identity",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("executor_id", sa.UUID(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.UUID(), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("outcome_code", sa.String(length=30), nullable=True),
        sa.Column("proof_class", sa.String(length=30), nullable=True),
        sa.Column("result_recorded_at", sa.DateTime(), nullable=True),
        sa.Column(
            "log_state",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "log_truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "log_size_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("log_expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "billing_mode",
            sa.String(length=20),
            nullable=False,
            server_default="zero_cost",
        ),
        sa.Column(
            "charged_credits",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("billing_transaction_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["environment_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["server_plans.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["volume_id"],
            ["volumes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns, unique, where in JOB_INDEXES:
        _create_index(name, JOB_TABLE, columns, unique, where)


def _create_logs() -> None:
    op.create_table(
        LOG_TABLE,
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "encoding",
            sa.String(length=20),
            nullable=False,
            server_default="utf-8",
        ),
        sa.Column(
            "truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], [f"{JOB_TABLE}.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    _create_index(
        "ix_batch_job_logs_expires_at",
        LOG_TABLE,
        ["expires_at"],
        False,
        None,
    )


def upgrade() -> None:
    # AUTO_CREATE_TABLES may have created current models before Alembic runs.
    tables = _tables()
    if JOB_TABLE not in tables:
        _create_jobs()
    else:
        for name, columns, unique, where in JOB_INDEXES:
            _create_index(name, JOB_TABLE, columns, unique, where)
    if LOG_TABLE not in _tables():
        _create_logs()
    else:
        _create_index(
            "ix_batch_job_logs_expires_at",
            LOG_TABLE,
            ["expires_at"],
            False,
            None,
        )


def downgrade() -> None:
    tables = _tables()
    if LOG_TABLE in tables:
        if "ix_batch_job_logs_expires_at" in _indexes(LOG_TABLE):
            op.drop_index("ix_batch_job_logs_expires_at", table_name=LOG_TABLE)
        op.drop_table(LOG_TABLE)
    if JOB_TABLE in tables:
        for name, _columns, _unique, _where in JOB_INDEXES:
            if name in _indexes(JOB_TABLE):
                op.drop_index(name, table_name=JOB_TABLE)
        op.drop_table(JOB_TABLE)
