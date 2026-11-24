"""add bounded recovery scan indexes

Revision ID: a4c9e2f7b1d3
Revises: c5f8a2d91e47
Create Date: 2026-11-22 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c9e2f7b1d3"
down_revision = "c5f8a2d91e47"
branch_labels = None
depends_on = None

LAUNCH_TABLE = "server_launch_operations"
LAUNCH_INDEX = "ix_server_launch_operations_recovery_scan"
LAUNCH_STATES = "state IN ('prepared', 'executing', 'uncertain')"

BACKUP_TABLE = "volume_backups"
BACKUP_INDEX = "ix_volume_backups_recovery_scan"
RESTORE_TABLE = "volume_restores"
RESTORE_INDEX = "ix_volume_restores_recovery_scan"
VOLUME_STATES = "status IN ('pending', 'in_progress', 'recovery_required')"

ENVIRONMENT_TABLE = "environment_revisions"
ENVIRONMENT_PREFLIGHT_REVISION = "c5f8a2d91e47"


def _indexes(table):
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _duplicate_environment_revisions():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(ENVIRONMENT_TABLE):
        return []
    return bind.execute(
        sa.text(
            "SELECT template_id, fingerprint, count(*) AS revision_count "
            f"FROM {ENVIRONMENT_TABLE} GROUP BY template_id, fingerprint "
            "HAVING count(*) > 1 ORDER BY template_id, fingerprint"
        )
    ).fetchall()


def _refuse_deeper_downgrade_with_duplicates():
    """Keep the environment-revision preflight ahead of index DDL.

    A full downgrade from this revision would otherwise drop the scan indexes
    before the older revision's duplicate preflight raises and rolls back.
    A one-step downgrade to the environment-revision revision is safe and does
    not need this check.
    """
    context = op.get_context()
    environment = getattr(context, "environment_context", None)
    if environment is None:
        return
    target = environment.get_revision_argument()
    if target in ("-1", revision, ENVIRONMENT_PREFLIGHT_REVISION):
        return
    duplicates = _duplicate_environment_revisions()
    if not duplicates:
        return
    sample = ", ".join(
        f"template_id={row[0]} fingerprint={row[1]} count={row[2]}" for row in duplicates[:5]
    )
    raise RuntimeError(
        "Cannot downgrade environment revisions: "
        f"{len(duplicates)} (template_id, fingerprint) group(s) contain duplicate rows, "
        "which the legacy unique constraint rejects. Resolve the duplicates "
        "(for example by restoring the pre-migration snapshot) before retrying. "
        "No revision rows were deleted or merged and no scan indexes were dropped. "
        f"Affected groups: {sample}"
    )


def _create_scan_index(index, table, where):
    if index in _indexes(table):
        return
    op.create_index(
        index,
        table,
        [sa.text("COALESCE(heartbeat_at, created_at)"), sa.text("id")],
        unique=False,
        postgresql_where=sa.text(where),
    )


def upgrade() -> None:
    _create_scan_index(LAUNCH_INDEX, LAUNCH_TABLE, LAUNCH_STATES)
    _create_scan_index(BACKUP_INDEX, BACKUP_TABLE, VOLUME_STATES)
    _create_scan_index(RESTORE_INDEX, RESTORE_TABLE, VOLUME_STATES)


def downgrade() -> None:
    _refuse_deeper_downgrade_with_duplicates()
    for table, index in (
        (LAUNCH_TABLE, LAUNCH_INDEX),
        (BACKUP_TABLE, BACKUP_INDEX),
        (RESTORE_TABLE, RESTORE_INDEX),
    ):
        if index in _indexes(table):
            op.drop_index(index, table_name=table)
