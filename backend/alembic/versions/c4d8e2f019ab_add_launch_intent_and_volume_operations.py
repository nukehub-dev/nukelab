"""add launch intent and volume operation foundations

Revision ID: c4d8e2f019ab
Revises: 34ce1a62ffe8
Create Date: 2026-11-15 14:11:49.015035

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "c4d8e2f019ab"
down_revision = "34ce1a62ffe8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AUTO_CREATE_TABLES may have created current models before Alembic runs.
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "environment_revisions" not in tables:
        _create_environment_revisions()
    if "volume_operations" not in tables:
        _create_volume_operations()
    if "server_launch_records" not in tables:
        _create_server_launch_records()
    _extend_queue(inspector)


def _create_environment_revisions() -> None:
    op.create_table(
        "environment_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("template_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("runtime_identity", sa.JSON(), nullable=False),
        sa.Column("toolchain_identity", sa.JSON(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["environment_templates.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "fingerprint"),
    )
    op.create_index(
        op.f("ix_environment_revisions_template_id"),
        "environment_revisions",
        ["template_id"],
        unique=False,
    )


def _create_volume_operations() -> None:
    op.create_table(
        "volume_operations",
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("volume_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("fencing_token", sa.UUID(), nullable=False),
        sa.Column("helper_identity", sa.String(length=255), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["volume_id"], ["volumes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("operation_id", "volume_id"),
    )
    op.create_index(
        "ix_volume_operations_active", "volume_operations", ["volume_id", "state"], unique=False
    )
    op.create_index(
        "uq_volume_operations_exclusive",
        "volume_operations",
        ["volume_id"],
        unique=True,
        postgresql_where=sa.text(
            "kind IN ('backup', 'restore') AND state IN ('reserved', 'running', 'recovery_required')"
        ),
    )


def _create_server_launch_records() -> None:
    op.create_table(
        "server_launch_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("actual_runtime_identity", sa.JSON(), nullable=False),
        sa.Column("actual_toolchain_identity", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["environment_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "generation"),
    )
    op.create_index(
        op.f("ix_server_launch_records_server_id"),
        "server_launch_records",
        ["server_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_server_launch_records_user_id"), "server_launch_records", ["user_id"], unique=False
    )


def _extend_queue(inspector) -> None:
    columns = {column["name"] for column in inspector.get_columns("server_queue")}
    indexes = {index["name"] for index in inspector.get_indexes("server_queue")}
    foreign_keys = inspector.get_foreign_keys("server_queue")

    def add_column(table_name, column):
        if column.name not in columns:
            op.add_column(table_name, column)

    add_column(
        "server_queue",
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    add_column("server_queue", sa.Column("request_version", sa.Integer(), nullable=True))
    add_column(
        "server_queue",
        sa.Column("plan_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    add_column("server_queue", sa.Column("revision_id", sa.UUID(), nullable=True))
    add_column(
        "server_queue", sa.Column("requested_gpu", sa.Integer(), server_default="0", nullable=False)
    )
    add_column("server_queue", sa.Column("expires_at", sa.DateTime(), nullable=True))
    add_column("server_queue", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    add_column("server_queue", sa.Column("claim_token", sa.UUID(), nullable=True))
    add_column("server_queue", sa.Column("server_id", sa.UUID(), nullable=True))
    add_column("server_queue", sa.Column("reason_code", sa.String(length=64), nullable=True))
    if "ix_server_queue_expires_at" not in indexes:
        op.create_index(
            op.f("ix_server_queue_expires_at"), "server_queue", ["expires_at"], unique=False
        )
    if not any(fk["constrained_columns"] == ["server_id"] for fk in foreign_keys):
        op.create_foreign_key(
            "fk_server_queue_server_id",
            "server_queue",
            "servers",
            ["server_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    op.drop_constraint("fk_server_queue_server_id", "server_queue", type_="foreignkey")
    op.drop_index(op.f("ix_server_queue_expires_at"), table_name="server_queue")
    op.drop_column("server_queue", "reason_code")
    op.drop_column("server_queue", "server_id")
    op.drop_column("server_queue", "claim_token")
    op.drop_column("server_queue", "claimed_at")
    op.drop_column("server_queue", "expires_at")
    op.drop_column("server_queue", "requested_gpu")
    op.drop_column("server_queue", "revision_id")
    op.drop_column("server_queue", "plan_snapshot")
    op.drop_column("server_queue", "request_version")
    op.drop_column("server_queue", "request_payload")
    op.drop_index(op.f("ix_server_launch_records_user_id"), table_name="server_launch_records")
    op.drop_index(op.f("ix_server_launch_records_server_id"), table_name="server_launch_records")
    op.drop_table("server_launch_records")
    op.drop_index(
        "uq_volume_operations_exclusive",
        table_name="volume_operations",
        postgresql_where=sa.text(
            "kind IN ('backup', 'restore') AND state IN ('reserved', 'running', 'recovery_required')"
        ),
    )
    op.drop_index("ix_volume_operations_active", table_name="volume_operations")
    op.drop_table("volume_operations")
    op.drop_index(op.f("ix_environment_revisions_template_id"), table_name="environment_revisions")
    op.drop_table("environment_revisions")
