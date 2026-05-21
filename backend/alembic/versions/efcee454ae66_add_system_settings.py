"""add_system_settings

Revision ID: efcee454ae66
Revises: c4f8a2e1b9d3
Create Date: 2026-05-22 01:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'efcee454ae66'
down_revision = 'c4f8a2e1b9d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('key', sa.String(255), primary_key=True, nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('system_settings')
