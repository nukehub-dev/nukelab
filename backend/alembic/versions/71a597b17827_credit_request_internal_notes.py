"""credit_request_internal_notes

Revision ID: 71a597b17827
Revises: c334ada4aab6
Create Date: 2026-08-13 02:30:00.000000

Adds credit_request_messages.is_internal (reviewer-only notes hidden from
the requester). The server_default backfills existing rows; it is dropped
again so the ORM default rules.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '71a597b17827'
down_revision = 'c334ada4aab6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'credit_request_messages',
        sa.Column(
            'is_internal',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill is implicit via server_default; drop it so new rows rely on
    # the ORM-side default instead of a database default.
    op.alter_column('credit_request_messages', 'is_internal', server_default=None)


def downgrade() -> None:
    op.drop_column('credit_request_messages', 'is_internal')
