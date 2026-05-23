"""add_login_events_table

Revision ID: 6b57d6afc67a
Revises: 7fb227cc15f5
Create Date: 2026-05-23 13:12:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '6b57d6afc67a'
down_revision = '7fb227cc15f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'login_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, index=True),
        sa.Column('method', sa.String(20), nullable=False, server_default='password'),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_login_events_timestamp_method', 'login_events', ['timestamp', 'method'])


def downgrade() -> None:
    op.drop_index('ix_login_events_timestamp_method', table_name='login_events')
    op.drop_table('login_events')
