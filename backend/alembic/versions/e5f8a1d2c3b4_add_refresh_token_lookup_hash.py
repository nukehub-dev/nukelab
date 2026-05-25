"""add_refresh_token_lookup_hash

Revision ID: e5f8a1d2c3b4
Revises: 6b57d6afc67a
Create Date: 2026-05-25 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5f8a1d2c3b4'
down_revision = '6b57d6afc67a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add deterministic SHA-256 lookup column for O(1) refresh token queries
    op.add_column('refresh_tokens', sa.Column('token_lookup', sa.String(length=64), nullable=True))

    # Index for fast exact-match lookup (core optimization for 100M+ users)
    op.create_index('ix_refresh_tokens_token_lookup', 'refresh_tokens', ['token_lookup'], unique=False)

    # Partial index: only active tokens per user (speeds up count/limit queries)
    op.execute("""
        CREATE INDEX ix_refresh_tokens_user_active
        ON refresh_tokens (user_id, created_at)
        WHERE revoked_at IS NULL
    """)

    # Drop useless btree index on bcrypt hashes — bcrypt is non-deterministic,
    # so the index can never be used for equality lookups.
    op.drop_index('ix_refresh_tokens_token_hash', table_name='refresh_tokens')


def downgrade() -> None:
    op.create_index('ix_refresh_tokens_token_hash', 'refresh_tokens', ['token_hash'], unique=False)
    op.drop_index('ix_refresh_tokens_user_active', table_name='refresh_tokens')
    op.drop_index('ix_refresh_tokens_token_lookup', table_name='refresh_tokens')
    op.drop_column('refresh_tokens', 'token_lookup')
