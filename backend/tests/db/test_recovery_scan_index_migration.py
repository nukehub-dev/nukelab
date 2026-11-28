# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Verify bounded recovery scan indexes on disposable PostgreSQL databases."""

import asyncio

from alembic.script import ScriptDirectory

from alembic import command
from tests.db.test_launch_workflow_migration import connect
from tests.db.test_launch_workflow_migration import migration_database as migration_database

PREVIOUS_REVISION = "c5f8a2d91e47"
SCAN_REVISION = "a4c9e2f7b1d3"
BATCH_REVISION = "b7d4e1c9a2f5"
ADMISSION_REVISION = "e2c7a9f4d6b1"
HEAD_REVISION = "f1a2b3c4d5e6"
INDEX_EXPECTATIONS = {
    "server_launch_operations": (
        "ix_server_launch_operations_recovery_scan",
        ("prepared", "executing", "uncertain"),
    ),
    "volume_backups": (
        "ix_volume_backups_recovery_scan",
        ("pending", "in_progress", "recovery_required"),
    ),
    "volume_restores": (
        "ix_volume_restores_recovery_scan",
        ("pending", "in_progress", "recovery_required"),
    ),
}


async def recovery_indexes(database):
    connection = await connect(database)
    try:
        rows = await connection.fetch(
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND indexname LIKE '%_recovery_scan'"
        )
        return {
            row["tablename"]: {
                "name": row["indexname"],
                "definition": row["indexdef"],
            }
            for row in rows
        }
    finally:
        await connection.close()


async def revision(database):
    connection = await connect(database)
    try:
        return await connection.fetchval("SELECT version_num FROM alembic_version")
    finally:
        await connection.close()


def test_recovery_scan_indexes_upgrade_downgrade_and_reupgrade(migration_database):
    config, database = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(SCAN_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(BATCH_REVISION).down_revision == SCAN_REVISION
    assert script.get_revision(ADMISSION_REVISION).down_revision == BATCH_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == ADMISSION_REVISION

    command.upgrade(config, "head")
    upgraded = asyncio.run(recovery_indexes(database))
    assert asyncio.run(revision(database)) == HEAD_REVISION
    assert set(upgraded) == set(INDEX_EXPECTATIONS)
    for table, (index_name, states) in INDEX_EXPECTATIONS.items():
        index = upgraded[table]
        assert index["name"] == index_name
        assert "(COALESCE(heartbeat_at, created_at), id)" in index["definition"]
        assert "WHERE" in index["definition"]
        for state in states:
            assert state in index["definition"]

    command.downgrade(config, SCAN_REVISION)
    assert asyncio.run(revision(database)) == SCAN_REVISION
    assert set(asyncio.run(recovery_indexes(database))) == set(INDEX_EXPECTATIONS)

    command.downgrade(config, PREVIOUS_REVISION)
    assert asyncio.run(revision(database)) == PREVIOUS_REVISION
    assert asyncio.run(recovery_indexes(database)) == {}

    command.upgrade(config, "head")
    reupgraded = asyncio.run(recovery_indexes(database))
    assert asyncio.run(revision(database)) == HEAD_REVISION
    assert set(reupgraded) == set(INDEX_EXPECTATIONS)
