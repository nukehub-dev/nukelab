"""merge_heads

Revision ID: 7fb227cc15f5
Revises: efcee454ae66, f3a8b2c1d4e5
Create Date: 2026-05-23 13:10:24.605215

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7fb227cc15f5'
down_revision = ('efcee454ae66', 'f3a8b2c1d4e5')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
