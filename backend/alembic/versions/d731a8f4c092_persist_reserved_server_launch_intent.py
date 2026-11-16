"""persist reserved server launch intent

Revision ID: d731a8f4c092
Revises: c4d8e2f019ab
Create Date: 2026-11-15 15:19:40.917936

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "d731a8f4c092"
down_revision = "c4d8e2f019ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Startup may create current model tables before Alembic runs.
    if "server_launch_intents" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "server_launch_intents",
        sa.Column("server_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("revision_id", sa.UUID(), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mounts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("gpu_devices", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("environment_slug", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("queue_id", sa.UUID(), nullable=True),
        sa.Column("claim_token", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["queue_id"], ["server_queue.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["environment_revisions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("server_id"),
    )


def downgrade() -> None:
    op.drop_table("server_launch_intents")
