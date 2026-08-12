"""credit_requests

Revision ID: 4172223ec2f8
Revises: 9f2c7a4e1b63
Create Date: 2026-08-12 17:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '4172223ec2f8'
down_revision = '9f2c7a4e1b63'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # If the table already exists (e.g., the app was started with
    # AUTO_CREATE_TABLES=true after the model was introduced but before this
    # migration ran), skip creation. Alembic still records this revision.
    conn = op.get_bind()
    inspector = inspect(conn)
    if 'credit_requests' in inspector.get_table_names():
        return

    op.create_table('credit_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('granted_amount', sa.Integer(), nullable=True),
    sa.Column('transaction_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_credit_requests_status'), 'credit_requests', ['status'], unique=False)
    op.create_index(op.f('ix_credit_requests_user_id'), 'credit_requests', ['user_id'], unique=False)
    # At most one pending request per user (authoritative race guard for
    # CreditRequestService.create_request).
    op.create_index(
        'uq_credit_requests_pending_per_user',
        'credit_requests',
        ['user_id'],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index('uq_credit_requests_pending_per_user', table_name='credit_requests')
    op.drop_index(op.f('ix_credit_requests_user_id'), table_name='credit_requests')
    op.drop_index(op.f('ix_credit_requests_status'), table_name='credit_requests')
    op.drop_table('credit_requests')
