"""credit_request_type

Revision ID: c334ada4aab6
Revises: fba51cd9b50f
Create Date: 2026-08-13 01:20:00.000000

Adds credit_requests.request_type ('top_up' default, 'allowance' for
daily-allowance change requests). The server_default keeps existing rows
valid; it is dropped again after backfill so the ORM default rules.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'c334ada4aab6'
down_revision = 'fba51cd9b50f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'credit_requests',
        sa.Column(
            'request_type',
            sa.String(length=20),
            nullable=False,
            server_default='top_up',
        ),
    )
    # Backfill is implicit via server_default; drop it so new rows rely on
    # the ORM-side default instead of a database default.
    op.alter_column('credit_requests', 'request_type', server_default=None)


def downgrade() -> None:
    op.drop_column('credit_requests', 'request_type')
