"""drop_volume_server_count

Revision ID: e8f7d6c5b4a3
Revises: fd33f829440e
Create Date: 2026-05-27 01:43:24.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8f7d6c5b4a3'
down_revision = 'fd33f829440e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('volumes', 'server_count')


def downgrade() -> None:
    op.add_column('volumes', sa.Column('server_count', sa.Integer(), nullable=True, server_default='0'))
