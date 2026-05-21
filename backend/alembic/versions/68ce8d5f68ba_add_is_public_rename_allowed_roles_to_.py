"""add is_public rename allowed_roles to visible_to_roles

Revision ID: 68ce8d5f68ba
Revises: 953bf4cd75cd
Create Date: 2026-05-21 06:41:57.818112

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '68ce8d5f68ba'
down_revision = '953bf4cd75cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column('server_plans', sa.Column('is_public', sa.Boolean(), nullable=True))
    op.add_column('server_plans', sa.Column('visible_to_roles', sa.JSON(), nullable=True))

    # Migrate data:
    # - If allowed_roles was empty [] or NULL → is_public = true, visible_to_roles = []
    # - Otherwise → is_public = false, visible_to_roles = allowed_roles
    op.execute("""
        UPDATE server_plans
        SET is_public = (allowed_roles::text = '[]' OR allowed_roles IS NULL),
            visible_to_roles = COALESCE(allowed_roles, '[]')
    """)

    # Drop old column
    op.drop_column('server_plans', 'allowed_roles')

    # Set defaults and make non-nullable
    op.alter_column('server_plans', 'is_public', server_default='false', nullable=False)
    op.alter_column('server_plans', 'visible_to_roles', server_default='[]', nullable=False)


def downgrade() -> None:
    # Re-add old column
    op.add_column('server_plans', sa.Column('allowed_roles', postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True))

    # Migrate data back:
    # - If is_public = true → allowed_roles = []
    # - Otherwise → allowed_roles = visible_to_roles
    op.execute("""
        UPDATE server_plans
        SET allowed_roles = CASE WHEN is_public THEN '[]' ELSE visible_to_roles END
    """)

    # Drop new columns
    op.drop_column('server_plans', 'visible_to_roles')
    op.drop_column('server_plans', 'is_public')
