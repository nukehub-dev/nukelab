"""add_maintenance_windows

Revision ID: a1b2c3d4e5f6
Revises: 90dab50c09de
Create Date: 2026-05-24 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '90dab50c09de'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'maintenance_windows',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('start_at', sa.DateTime(), nullable=False),
        sa.Column('end_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('notified_at', sa.DateTime(), nullable=True),
        sa.Column('auto_enabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('auto_disabled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )
    op.create_index('ix_maintenance_windows_start_at', 'maintenance_windows', ['start_at'])
    op.create_index('ix_maintenance_windows_is_active', 'maintenance_windows', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_maintenance_windows_is_active', table_name='maintenance_windows')
    op.drop_index('ix_maintenance_windows_start_at', table_name='maintenance_windows')
    op.drop_table('maintenance_windows')
