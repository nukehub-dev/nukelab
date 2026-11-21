"""add recovery executor heartbeat registry

Revision ID: b1e7c4a9d2f6
Revises: f6b29a41d7c8
Create Date: 2026-11-21 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b1e7c4a9d2f6"
down_revision = "f6b29a41d7c8"
branch_labels = None
depends_on = None

OPERATION_TABLES = ("server_launch_operations", "volume_backups", "volume_restores")


def _columns(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _add_column(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("worker_heartbeats"):
        op.create_table(
            "worker_heartbeats",
            sa.Column("executor_id", sa.UUID(), nullable=False),
            sa.Column("hostname", sa.String(length=255), nullable=False),
            sa.Column("container_id", sa.String(length=255), nullable=True),
            sa.Column("container_started_at", sa.String(length=64), nullable=True),
            sa.Column("pid", sa.Integer(), nullable=False),
            sa.Column("process_start_time", sa.String(length=64), nullable=True),
            sa.Column("single_process_container", sa.Boolean(), nullable=False),
            sa.Column("schema_version", sa.String(length=32), nullable=False),
            sa.Column("state", sa.String(length=16), nullable=False),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("executor_id"),
        )
    if "ix_worker_heartbeats_state_heartbeat_at" not in _indexes("worker_heartbeats"):
        op.create_index(
            "ix_worker_heartbeats_state_heartbeat_at",
            "worker_heartbeats",
            ["state", "heartbeat_at"],
            unique=False,
        )
    for table in OPERATION_TABLES:
        _add_column(table, sa.Column("executor_id", sa.UUID(), nullable=True))
        _add_column(table, sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        index_name = f"ix_{table}_executor_id"
        if index_name not in _indexes(table):
            op.create_index(index_name, table, ["executor_id"], unique=False)


def downgrade() -> None:
    for table in OPERATION_TABLES:
        index_name = f"ix_{table}_executor_id"
        if index_name in _indexes(table):
            op.drop_index(index_name, table_name=table)
        columns = _columns(table)
        if "heartbeat_at" in columns:
            op.drop_column(table, "heartbeat_at")
        if "executor_id" in columns:
            op.drop_column(table, "executor_id")
    if sa.inspect(op.get_bind()).has_table("worker_heartbeats"):
        if "ix_worker_heartbeats_state_heartbeat_at" in _indexes("worker_heartbeats"):
            op.drop_index("ix_worker_heartbeats_state_heartbeat_at", table_name="worker_heartbeats")
        op.drop_table("worker_heartbeats")
