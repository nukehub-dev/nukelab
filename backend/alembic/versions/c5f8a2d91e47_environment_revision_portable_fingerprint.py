"""add portable revision fingerprint and active-only uniqueness

Revision ID: c5f8a2d91e47
Revises: b1e7c4a9d2f6
Create Date: 2026-11-21 15:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "c5f8a2d91e47"
down_revision = "b1e7c4a9d2f6"
branch_labels = None
depends_on = None

TABLE = "environment_revisions"
PORTABLE_COLUMN = "portable_fingerprint"
PORTABLE_INDEX = "ix_environment_revisions_portable_fingerprint"
ACTIVE_FINGERPRINT_INDEX = "uq_environment_revisions_active_fingerprint"
LEGACY_UNIQUE_CONSTRAINT = "uq_environment_revisions_template_fingerprint"


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(inspector):
    return {item["name"] for item in inspector.get_columns(TABLE)}


def _indexes(inspector):
    return {item["name"] for item in inspector.get_indexes(TABLE)}


def _has_legacy_unique_constraint(inspector):
    return any(
        list(item.get("column_names") or []) == ["template_id", "fingerprint"]
        for item in inspector.get_unique_constraints(TABLE)
    )


def upgrade() -> None:
    inspector = _inspector()
    if not inspector.has_table(TABLE):
        return
    if PORTABLE_COLUMN not in _columns(inspector):
        op.add_column(TABLE, sa.Column(PORTABLE_COLUMN, sa.String(length=64), nullable=True))
    if PORTABLE_INDEX not in _indexes(inspector):
        op.create_index(PORTABLE_INDEX, TABLE, [PORTABLE_COLUMN], unique=False)

    inspector = _inspector()
    for constraint in inspector.get_unique_constraints(TABLE):
        if list(constraint.get("column_names") or []) == ["template_id", "fingerprint"]:
            name = constraint.get("name")
            if name:
                op.drop_constraint(name, TABLE, type_="unique")

    inspector = _inspector()
    if ACTIVE_FINGERPRINT_INDEX not in _indexes(inspector):
        op.create_index(
            ACTIVE_FINGERPRINT_INDEX,
            TABLE,
            ["template_id", "fingerprint"],
            unique=True,
            postgresql_where=sa.text("revoked = false"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = _inspector()
    if not inspector.has_table(TABLE):
        return

    duplicates = bind.execute(
        sa.text(
            "SELECT template_id, fingerprint, count(*) AS revision_count "
            f"FROM {TABLE} GROUP BY template_id, fingerprint "
            "HAVING count(*) > 1 ORDER BY template_id, fingerprint"
        )
    ).fetchall()
    if duplicates:
        sample = ", ".join(
            f"template_id={row[0]} fingerprint={row[1]} count={row[2]}" for row in duplicates[:5]
        )
        raise RuntimeError(
            "Cannot downgrade environment revisions: "
            f"{len(duplicates)} (template_id, fingerprint) group(s) contain duplicate rows, "
            "which the legacy unique constraint rejects. Resolve the duplicates "
            "(for example by restoring the pre-migration snapshot) before retrying. "
            "No revision rows were deleted or merged. "
            f"Affected groups: {sample}"
        )

    indexes = _indexes(inspector)
    if ACTIVE_FINGERPRINT_INDEX in indexes:
        op.drop_index(ACTIVE_FINGERPRINT_INDEX, table_name=TABLE)
    if PORTABLE_INDEX in indexes:
        op.drop_index(PORTABLE_INDEX, table_name=TABLE)
    if PORTABLE_COLUMN in _columns(inspector):
        op.drop_column(TABLE, PORTABLE_COLUMN)

    inspector = _inspector()
    if not _has_legacy_unique_constraint(inspector):
        op.create_unique_constraint(
            LEGACY_UNIQUE_CONSTRAINT,
            TABLE,
            ["template_id", "fingerprint"],
        )
