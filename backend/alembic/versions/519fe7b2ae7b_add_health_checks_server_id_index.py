"""add_health_checks_server_id_index

Revision ID: 519fe7b2ae7b
Revises: f3a8b2c1d4e5
Create Date: 2026-05-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '519fe7b2ae7b'
down_revision = 'f3a8b2c1d4e5'
branch_labels = None
depends_on = None


def index_exists(table_name, index_name):
    """Check if an index already exists."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM pg_indexes WHERE tablename = :table AND indexname = :index"
    ), {"table": table_name, "index": index_name})
    return result.scalar() is not None


def upgrade() -> None:
    if not index_exists('health_checks', 'ix_health_checks_server_checked_at'):
        op.create_index(
            'ix_health_checks_server_checked_at',
            'health_checks',
            ['server_id', 'checked_at'],
            unique=False
        )


def downgrade() -> None:
    if index_exists('health_checks', 'ix_health_checks_server_checked_at'):
        op.drop_index('ix_health_checks_server_checked_at', table_name='health_checks')
