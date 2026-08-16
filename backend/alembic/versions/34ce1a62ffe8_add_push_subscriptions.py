"""add_push_subscriptions

Revision ID: 34ce1a62ffe8
Revises: 0b7a7bf41017
Create Date: 2026-08-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "34ce1a62ffe8"
down_revision: str | None = "0b7a7bf41017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    if "push_subscriptions" not in table_names:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("keys", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_push_subscriptions_user_id"),
            "push_subscriptions",
            ["user_id"],
            unique=False,
        )
        # Endpoints are unique per user. Push endpoints are treated as secrets
        # and must never be logged.
        op.create_index(
            "uq_push_subscriptions_endpoint_per_user",
            "push_subscriptions",
            ["user_id", "endpoint"],
            unique=True,
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    if "push_subscriptions" in table_names:
        op.drop_index(
            "uq_push_subscriptions_endpoint_per_user",
            table_name="push_subscriptions",
        )
        op.drop_index(
            op.f("ix_push_subscriptions_user_id"),
            table_name="push_subscriptions",
        )
        op.drop_table("push_subscriptions")
