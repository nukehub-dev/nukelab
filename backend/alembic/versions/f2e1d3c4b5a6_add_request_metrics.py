"""add_request_metrics

Revision ID: f2e1d3c4b5a6
Revises: d9c8b7a6e5f4
Create Date: 2026-06-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f2e1d3c4b5a6'
down_revision = 'd9c8b7a6e5f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'request_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('path', sa.String(255), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('duration_ms', sa.Float(), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('ip_address', postgresql.INET(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_request_metrics_path', 'request_metrics', ['path'])
    op.create_index('ix_request_metrics_status_code', 'request_metrics', ['status_code'])
    op.create_index('ix_request_metrics_user_id', 'request_metrics', ['user_id'])
    op.create_index('ix_request_metrics_correlation_id', 'request_metrics', ['correlation_id'])
    op.create_index('ix_request_metrics_path_status', 'request_metrics', ['path', 'status_code'])
    op.create_index('ix_request_metrics_created_at', 'request_metrics', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_request_metrics_created_at', table_name='request_metrics')
    op.drop_index('ix_request_metrics_path_status', table_name='request_metrics')
    op.drop_index('ix_request_metrics_correlation_id', table_name='request_metrics')
    op.drop_index('ix_request_metrics_user_id', table_name='request_metrics')
    op.drop_index('ix_request_metrics_status_code', table_name='request_metrics')
    op.drop_index('ix_request_metrics_path', table_name='request_metrics')
    op.drop_table('request_metrics')
