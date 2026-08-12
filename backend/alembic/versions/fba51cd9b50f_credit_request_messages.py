"""credit_request_messages

Revision ID: fba51cd9b50f
Revises: 4172223ec2f8
Create Date: 2026-08-13 00:30:00.000000

Adds the credit_request_messages conversation table and widens the
one-open-request-per-user partial unique index to cover both open states
(pending and needs_info).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'fba51cd9b50f'
down_revision = '4172223ec2f8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    # Widen the open-state guard: one open request per user across
    # 'pending' and 'needs_info'.
    op.drop_index('uq_credit_requests_pending_per_user', table_name='credit_requests')
    op.create_index(
        'uq_credit_requests_pending_per_user',
        'credit_requests',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'needs_info')"),
    )

    # Idempotent create (matches the AUTO_CREATE_TABLES guard style of the
    # previous revisions).
    if 'credit_request_messages' in inspector.get_table_names():
        return

    op.create_table('credit_request_messages',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('request_id', sa.UUID(), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['credit_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credit_request_messages_request_id'), 'credit_request_messages', ['request_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_credit_request_messages_request_id'), table_name='credit_request_messages')
    op.drop_table('credit_request_messages')

    # Restore the pending-only open-state guard.
    op.drop_index('uq_credit_requests_pending_per_user', table_name='credit_requests')
    op.create_index(
        'uq_credit_requests_pending_per_user',
        'credit_requests',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
