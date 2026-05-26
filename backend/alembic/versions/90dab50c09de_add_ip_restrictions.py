"""add_ip_restrictions

Revision ID: 90dab50c09de
Revises: cba3fd7d54fd
Create Date: 2026-05-26 07:09:05.960760

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '90dab50c09de'
down_revision = 'cba3fd7d54fd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'ip_restrictions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('ip_range', sa.String(length=50), nullable=False),
        sa.Column('restriction_type', sa.String(length=10), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_by_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index(
        'ix_ip_restrictions_type_active',
        'ip_restrictions',
        ['restriction_type', 'is_active'],
    )


def downgrade() -> None:
    op.drop_index('ix_ip_restrictions_type_active', table_name='ip_restrictions')
    op.drop_table('ip_restrictions')
