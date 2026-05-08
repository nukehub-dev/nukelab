"""Add billing and expiration fields to servers

Revision ID: 001_add_server_billing_fields
Revises: 
Create Date: 2026-05-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_add_server_billing_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add billing and expiration fields to servers table
    op.add_column('servers', sa.Column('total_cost', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('servers', sa.Column('last_billed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('servers', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    
    # Add before/after state to activity_logs
    op.add_column('activity_logs', sa.Column('before_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'))
    op.add_column('activity_logs', sa.Column('after_state', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'))
    op.add_column('activity_logs', sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Create server_schedules table
    op.create_table(
        'server_schedules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('cron_expression', sa.String(100), nullable=False),
        sa.Column('timezone', sa.String(50), server_default='UTC'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_schedules_server', 'server_schedules', ['server_id'])
    op.create_index('idx_schedules_next_run', 'server_schedules', ['next_run_at'], postgresql_where=sa.text('is_active = true'))
    
    # Create shared_workspaces table
    op.create_table(
        'shared_workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('volume_name', sa.String(255), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), onupdate=sa.text('NOW()')),
    )
    
    # Create workspace_members table
    op.create_table(
        'workspace_members',
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('shared_workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), server_default='read_write'),
        sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('workspace_id', 'user_id')
    )
    
    # Create volume_backups table
    op.create_table(
        'volume_backups',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('volume_name', sa.String(255), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('backup_path', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_backups_user', 'volume_backups', ['user_id'])
    op.create_index('idx_backups_volume', 'volume_backups', ['volume_name'])


def downgrade():
    # Drop new tables
    op.drop_index('idx_backups_volume', table_name='volume_backups')
    op.drop_index('idx_backups_user', table_name='volume_backups')
    op.drop_table('volume_backups')
    op.drop_table('workspace_members')
    op.drop_table('shared_workspaces')
    op.drop_index('idx_schedules_next_run', table_name='server_schedules')
    op.drop_index('idx_schedules_server', table_name='server_schedules')
    op.drop_table('server_schedules')
    
    # Drop columns from activity_logs
    op.drop_column('activity_logs', 'request_id')
    op.drop_column('activity_logs', 'after_state')
    op.drop_column('activity_logs', 'before_state')
    
    # Drop columns from servers
    op.drop_column('servers', 'expires_at')
    op.drop_column('servers', 'last_billed_at')
    op.drop_column('servers', 'total_cost')
