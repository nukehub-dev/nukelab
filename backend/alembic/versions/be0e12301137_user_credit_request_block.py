"""user_credit_request_block

Revision ID: be0e12301137
Revises: 71a597b17827
Create Date: 2026-08-13 03:20:00.000000

Adds users.credit_requests_blocked (admin-imposed per-user block on
creating credit requests). The server_default backfills existing rows;
it is dropped again so the ORM default rules.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'be0e12301137'
down_revision = '71a597b17827'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column(
            'credit_requests_blocked',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Backfill is implicit via server_default; drop it so new rows rely on
    # the ORM-side default instead of a database default.
    op.alter_column('users', 'credit_requests_blocked', server_default=None)


def downgrade() -> None:
    op.drop_column('users', 'credit_requests_blocked')
