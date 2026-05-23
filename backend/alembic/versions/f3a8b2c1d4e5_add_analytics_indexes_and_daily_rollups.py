"""add_analytics_indexes_and_daily_rollups

Revision ID: f3a8b2c1d4e5
Revises: bd6b483e5c06
Create Date: 2026-05-23 08:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f3a8b2c1d4e5'
down_revision = 'bd6b483e5c06'
branch_labels = None
depends_on = None


def index_exists(table_name, index_name):
    """Check if an index already exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE tablename = :table AND indexname = :index"
    ), {"table": table_name, "index": index_name})
    return result.scalar() is not None


def table_exists(table_name):
    """Check if a table already exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = :table"
    ), {"table": table_name})
    return result.scalar() is not None


def upgrade() -> None:
    # Create daily_server_metrics table if not exists
    if not table_exists('daily_server_metrics'):
        op.create_table(
            'daily_server_metrics',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
            sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False),
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('avg_cpu', sa.Float(), nullable=True),
            sa.Column('peak_cpu', sa.Float(), nullable=True),
            sa.Column('avg_memory', sa.Float(), nullable=True),
            sa.Column('peak_memory', sa.Float(), nullable=True),
            sa.Column('avg_network_rx', sa.BigInteger(), nullable=True),
            sa.Column('avg_network_tx', sa.BigInteger(), nullable=True),
            sa.Column('avg_disk_read', sa.BigInteger(), nullable=True),
            sa.Column('avg_disk_write', sa.BigInteger(), nullable=True),
            sa.Column('avg_gpu', sa.Float(), nullable=True),
            sa.Column('peak_gpu', sa.Float(), nullable=True),
            sa.Column('data_points', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
            sa.UniqueConstraint('server_id', 'date', name='uq_daily_server_metrics_server_id_date'),
        )
    if not index_exists('daily_server_metrics', 'ix_daily_server_metrics_server_id_date'):
        op.create_index('ix_daily_server_metrics_server_id_date', 'daily_server_metrics', ['server_id', 'date'])

    # Add indexes for analytics queries (idempotent)
    if not index_exists('server_metrics', 'ix_server_metrics_collected_at'):
        op.create_index('ix_server_metrics_collected_at', 'server_metrics', ['collected_at'])
    if not index_exists('server_metrics', 'ix_server_metrics_server_id_collected_at'):
        op.create_index('ix_server_metrics_server_id_collected_at', 'server_metrics', ['server_id', 'collected_at'])
    if not index_exists('system_metrics', 'ix_system_metrics_collected_at'):
        op.create_index('ix_system_metrics_collected_at', 'system_metrics', ['collected_at'])
    if not index_exists('credit_transactions', 'ix_credit_transactions_created_at'):
        op.create_index('ix_credit_transactions_created_at', 'credit_transactions', ['created_at'])
    if not index_exists('activity_logs', 'ix_activity_logs_created_at'):
        op.create_index('ix_activity_logs_created_at', 'activity_logs', ['created_at'])
    if not index_exists('health_checks', 'ix_health_checks_checked_at'):
        op.create_index('ix_health_checks_checked_at', 'health_checks', ['checked_at'])
    if not index_exists('alert_history', 'ix_alert_history_created_at'):
        op.create_index('ix_alert_history_created_at', 'alert_history', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_alert_history_created_at', table_name='alert_history')
    op.drop_index('ix_health_checks_checked_at', table_name='health_checks')
    op.drop_index('ix_activity_logs_created_at', table_name='activity_logs')
    op.drop_index('ix_credit_transactions_created_at', table_name='credit_transactions')
    op.drop_index('ix_system_metrics_collected_at', table_name='system_metrics')
    op.drop_index('ix_server_metrics_server_id_collected_at', table_name='server_metrics')
    op.drop_index('ix_server_metrics_collected_at', table_name='server_metrics')
    op.drop_index('ix_daily_server_metrics_server_id_date', table_name='daily_server_metrics')
    op.drop_table('daily_server_metrics')
