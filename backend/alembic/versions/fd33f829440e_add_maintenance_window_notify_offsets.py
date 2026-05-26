"""add_maintenance_window_notify_offsets

Revision ID: fd33f829440e
Revises: a1b2c3d4e5f6
Create Date: 2026-05-26 19:20:16.601230

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fd33f829440e'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('maintenance_windows', sa.Column('notify_offsets', sa.JSON(), nullable=True))
    op.add_column('maintenance_windows', sa.Column('notified_offsets', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('maintenance_windows', 'notified_offsets')
    op.drop_column('maintenance_windows', 'notify_offsets')
