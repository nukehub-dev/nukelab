"""gpu_allocations

Revision ID: 9f2c7a4e1b63
Revises: 8298b4bb8ada
Create Date: 2026-07-20 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '9f2c7a4e1b63'
down_revision = '8298b4bb8ada'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # If the table already exists (e.g., the app was started with
    # AUTO_CREATE_TABLES=true after the model was introduced but before this
    # migration ran), skip creation. Alembic still records this revision.
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'gpu_allocations' in inspector.get_table_names():
        return

    op.create_table('gpu_allocations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('server_id', sa.UUID(), nullable=False),
    sa.Column('device', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('device')
    )
    op.create_index(op.f('ix_gpu_allocations_server_id'), 'gpu_allocations', ['server_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_gpu_allocations_server_id'), table_name='gpu_allocations')
    op.drop_table('gpu_allocations')
