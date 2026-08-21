# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Startup schema-compatibility guard.

Detects when the database Alembic revision is newer than the revisions known to
the running backend image, which is the rollback hazard surfaced by pull-based
deploys.
"""

import os
from dataclasses import dataclass

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger

logger = get_logger(__name__)

ALEMBIC_VERSION_QUERY = text("SELECT version_num FROM alembic_version")


@dataclass(frozen=True)
class SchemaCompatibilityResult:
    """Result of a schema-compatibility check."""

    ok: bool
    unknown_revisions: tuple[str, ...]
    db_revisions: tuple[str, ...]
    known_revisions: frozenset[str]
    db_unreachable: bool = False


async def check_schema_compatibility(
    engine: AsyncEngine,
    script_dir_path: str | os.PathLike[str],
) -> SchemaCompatibilityResult:
    """Check whether the DB schema revision is known to this backend image.

    Returns a result indicating compatibility. A DB revision that is absent from
    the local ScriptDirectory means the schema is newer than the code (rollback
    hazard). No ``alembic_version`` table or an empty ``alembic_version`` is
    treated as a fresh/unmanaged database and is considered compatible.

    If the database cannot be reached, the guard degrades gracefully: it logs a
    warning and returns a result with ``db_unreachable=True`` and ``ok=True`` so
    startup is not blocked by a transient DB outage.
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(ALEMBIC_VERSION_QUERY)
            db_revisions = tuple(row[0] for row in result)
    except Exception as exc:
        logger.warning(f"Schema guard could not reach database: {exc}")
        return SchemaCompatibilityResult(
            ok=True,
            unknown_revisions=(),
            db_revisions=(),
            known_revisions=frozenset(),
            db_unreachable=True,
        )

    if not db_revisions:
        # Fresh or unmanaged database.
        return SchemaCompatibilityResult(
            ok=True,
            unknown_revisions=(),
            db_revisions=(),
            known_revisions=frozenset(),
        )

    try:
        script_dir = ScriptDirectory(str(script_dir_path))
        known_revisions = frozenset(rev.revision for rev in script_dir.walk_revisions())
    except Exception as exc:
        logger.warning(f"Schema guard could not load Alembic script directory: {exc}")
        return SchemaCompatibilityResult(
            ok=True,
            unknown_revisions=(),
            db_revisions=db_revisions,
            known_revisions=frozenset(),
            db_unreachable=False,
        )

    unknown_revisions = tuple(r for r in db_revisions if r not in known_revisions)
    return SchemaCompatibilityResult(
        ok=not unknown_revisions,
        unknown_revisions=unknown_revisions,
        db_revisions=db_revisions,
        known_revisions=known_revisions,
    )


def _recovery_action() -> str:
    return (
        "Restore a pre-migrate backup or deploy a newer image "
        "matching the database schema revision."
    )


async def run_schema_guard(
    engine: AsyncEngine,
    script_dir_path: str | os.PathLike[str],
    mode: str,
    app_env: str,
) -> None:
    """Run the guard and raise on a rollback hazard when configured to refuse.

    ``mode`` must be one of ``off``, ``auto``, or ``enforce``. ``app_env`` is
    the resolved application environment (e.g. ``production`` or
    ``development``).
    """
    if mode == "off":
        return

    result = await check_schema_compatibility(engine, script_dir_path)
    if result.ok or not result.unknown_revisions:
        return

    recovery_action = _recovery_action()
    if mode == "enforce" or (mode == "auto" and app_env == "production"):
        logger.error(
            "Database schema is newer than this backend image; refusing to start",
            extra={
                "unknown_db_revisions": list(result.unknown_revisions),
                "recovery_action": recovery_action,
            },
        )
        raise RuntimeError(
            f"Database schema revision(s) {list(result.unknown_revisions)} "
            f"are newer than this backend image. {recovery_action}"
        )

    logger.warning(
        "Database schema is newer than this backend image",
        extra={
            "unknown_db_revisions": list(result.unknown_revisions),
            "recovery_action": recovery_action,
        },
    )
