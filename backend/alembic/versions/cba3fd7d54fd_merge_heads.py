"""merge_heads

Revision ID: cba3fd7d54fd
Revises: 519fe7b2ae7b, e5f8a1d2c3b4
Create Date: 2026-05-26 07:08:59.104431

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cba3fd7d54fd'
down_revision = ('519fe7b2ae7b', 'e5f8a1d2c3b4')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
