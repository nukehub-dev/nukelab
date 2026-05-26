"""drop_plan_requires_approval

Revision ID: d9c8b7a6e5f4
Revises: e8f7d6c5b4a3
Create Date: 2026-05-27 01:43:24.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd9c8b7a6e5f4'
down_revision = 'e8f7d6c5b4a3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column('server_plans', 'requires_approval')


def downgrade() -> None:
    op.add_column('server_plans', sa.Column('requires_approval', sa.Boolean(), nullable=True, server_default='false'))
