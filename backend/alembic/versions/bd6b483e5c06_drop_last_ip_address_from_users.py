"""drop_last_ip_address_from_users

Revision ID: bd6b483e5c06
Revises: 68ce8d5f68ba
Create Date: 2026-05-21 10:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bd6b483e5c06'
down_revision = '68ce8d5f68ba'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('users', 'last_ip_address')


def downgrade() -> None:
    op.add_column('users', sa.Column('last_ip_address', sa.dialects.postgresql.INET(), nullable=True))
