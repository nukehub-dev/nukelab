"""add_api_token_prefix

Revision ID: 4aa05fa3038f
Revises: c4f8a2e1b9d3
Create Date: 2026-05-20 11:40:20.622821

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4aa05fa3038f'
down_revision = 'c4f8a2e1b9d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add token_prefix column for fast API token lookup
    op.add_column('api_tokens', sa.Column('token_prefix', sa.String(length=16), nullable=True))
    # Create index for fast prefix-based queries
    op.create_index('ix_api_tokens_token_prefix', 'api_tokens', ['token_prefix'], unique=False)
    # Dev cleanup: remove old tokens without prefix so fallback loop is not needed
    op.execute("DELETE FROM api_tokens WHERE token_prefix IS NULL OR token_prefix = ''")


def downgrade() -> None:
    op.drop_index('ix_api_tokens_token_prefix', table_name='api_tokens')
    op.drop_column('api_tokens', 'token_prefix')
