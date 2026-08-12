"""credit_requests

Revision ID: 0af8d939f206
Revises: 9f2c7a4e1b63
Create Date: 2026-08-13 05:00:00.000000

Squashed credit-request schema (replaces the never-deployed 5-revision
chain): the credit_requests and credit_request_messages tables at their
final state, plus users.credit_requests_blocked.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '0af8d939f206'
down_revision = '9f2c7a4e1b63'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    # Idempotent creates (matches the AUTO_CREATE_TABLES guard style of the
    # previous revisions).
    if 'credit_requests' not in table_names:
        op.create_table('credit_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('request_type', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by', sa.UUID(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
        sa.Column('granted_amount', sa.Integer(), nullable=True),
        # Plain column, no FK: credit_transactions is range-partitioned and
        # cannot be referenced by a foreign key.
        sa.Column('transaction_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_credit_requests_status'), 'credit_requests', ['status'], unique=False)
        op.create_index(op.f('ix_credit_requests_user_id'), 'credit_requests', ['user_id'], unique=False)
        # At most one open (pending or needs_info) request per user; the
        # authoritative race guard for CreditRequestService.create_request.
        op.create_index(
            'uq_credit_requests_pending_per_user',
            'credit_requests',
            ['user_id'],
            unique=True,
            postgresql_where=sa.text("status IN ('pending', 'needs_info')"),
        )

    if 'credit_request_messages' not in table_names:
        op.create_table('credit_request_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('request_id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('is_internal', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['request_id'], ['credit_requests.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_credit_request_messages_request_id'), 'credit_request_messages', ['request_id'], unique=False)

    # Per-user credit request block. server_default backfills existing
    # rows; it is dropped again so the ORM default rules.
    user_columns = {c['name'] for c in inspector.get_columns('users')}
    if 'credit_requests_blocked' not in user_columns:
        op.add_column(
            'users',
            sa.Column(
                'credit_requests_blocked',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.alter_column('users', 'credit_requests_blocked', server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    table_names = inspector.get_table_names()

    user_columns = {c['name'] for c in inspector.get_columns('users')}
    if 'credit_requests_blocked' in user_columns:
        op.drop_column('users', 'credit_requests_blocked')

    if 'credit_request_messages' in table_names:
        op.drop_index(op.f('ix_credit_request_messages_request_id'), table_name='credit_request_messages')
        op.drop_table('credit_request_messages')

    if 'credit_requests' in table_names:
        op.drop_index('uq_credit_requests_pending_per_user', table_name='credit_requests')
        op.drop_index(op.f('ix_credit_requests_user_id'), table_name='credit_requests')
        op.drop_index(op.f('ix_credit_requests_status'), table_name='credit_requests')
        op.drop_table('credit_requests')
