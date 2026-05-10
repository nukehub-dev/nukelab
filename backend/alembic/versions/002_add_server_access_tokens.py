"""Add server access tokens table for production container auth

Revision ID: 002_add_server_access_tokens
Revises: 001_add_server_billing_fields
Create Date: 2026-05-10

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_add_server_access_tokens'
down_revision = '001_add_server_billing_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Create server_access_tokens table
    op.create_table(
        'server_access_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('servers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('jti', sa.String(64), nullable=False, unique=True),
        sa.Column('key_id', sa.String(32), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.String(255), nullable=True),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('use_count', sa.Integer(), server_default='0'),
        sa.Column('client_ip', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('token_type', sa.String(20), server_default='session'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    
    # Create indexes for performance
    op.create_index('idx_server_access_tokens_jti', 'server_access_tokens', ['jti'], unique=True)
    op.create_index('idx_server_access_tokens_server_user', 'server_access_tokens', ['server_id', 'user_id'])
    op.create_index('idx_server_access_tokens_expires', 'server_access_tokens', ['expires_at'])
    op.create_index('idx_server_access_tokens_revoked', 'server_access_tokens', ['revoked_at'])
    
    # Create index for cleanup queries
    op.create_index(
        'idx_server_access_tokens_cleanup',
        'server_access_tokens',
        ['expires_at'],
        postgresql_where=sa.text('revoked_at IS NULL')
    )


def downgrade():
    op.drop_index('idx_server_access_tokens_cleanup', table_name='server_access_tokens')
    op.drop_index('idx_server_access_tokens_revoked', table_name='server_access_tokens')
    op.drop_index('idx_server_access_tokens_expires', table_name='server_access_tokens')
    op.drop_index('idx_server_access_tokens_server_user', table_name='server_access_tokens')
    op.drop_index('idx_server_access_tokens_jti', table_name='server_access_tokens')
    op.drop_table('server_access_tokens')
