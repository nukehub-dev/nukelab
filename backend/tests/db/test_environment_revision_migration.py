# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Rehearse portable revision identity and active-only uniqueness migrations."""

import asyncio
import uuid
from datetime import datetime

import asyncpg
import pytest
from alembic.script import ScriptDirectory

from alembic import command
from tests.db.test_launch_workflow_migration import connect
from tests.db.test_launch_workflow_migration import migration_database as migration_database

PREVIOUS_REVISION = "b1e7c4a9d2f6"
PORTABLE_REVISION = "c5f8a2d91e47"
SCAN_REVISION = "a4c9e2f7b1d3"
BATCH_REVISION = "b7d4e1c9a2f5"
HEAD_REVISION = "e2c7a9f4d6b1"
PORTABLE_COLUMN = "portable_fingerprint"
PORTABLE_INDEX = "ix_environment_revisions_portable_fingerprint"
ACTIVE_FINGERPRINT_INDEX = "uq_environment_revisions_active_fingerprint"


async def schema_state(database):
    connection = await connect(database)
    try:
        columns = {
            row["column_name"]: row
            for row in await connection.fetch(
                "SELECT column_name, is_nullable, data_type, character_maximum_length "
                "FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='environment_revisions'"
            )
        }
        indexes = {
            row["indexname"]: row["indexdef"]
            for row in await connection.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' AND tablename='environment_revisions'"
            )
        }
        constraints = {
            row["conname"]: row["definition"]
            for row in await connection.fetch(
                "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                "WHERE conrelid = 'environment_revisions'::regclass AND contype='u'"
            )
        }
        return {
            "revision": await connection.fetchval("SELECT version_num FROM alembic_version"),
            "columns": columns,
            "indexes": indexes,
            "constraints": constraints,
            "revision_count": await connection.fetchval(
                "SELECT count(*) FROM environment_revisions"
            ),
        }
    finally:
        await connection.close()


async def insert_template(connection):
    template_id = uuid.uuid4()
    suffix = template_id.hex
    await connection.execute(
        "INSERT INTO environment_templates (id,name,slug,image) VALUES ($1,$2,$2,$3)",
        template_id,
        "environment-" + suffix,
        "workspace:latest",
    )
    return template_id


async def insert_revision(
    connection,
    template_id,
    *,
    template_fingerprint="d" * 64,
    fingerprint_value=None,
    revoked=False,
    created_at=datetime(2026, 1, 1, 12),
    portable_fingerprint=None,
    include_portable=True,
):
    revision_id = uuid.uuid4()
    fingerprint_value = fingerprint_value or uuid.uuid4().hex * 2
    if not include_portable:
        await connection.execute(
            "INSERT INTO environment_revisions "
            "(id,template_id,fingerprint,template_fingerprint,"
            "configuration,runtime_identity,toolchain_identity,revoked,created_at) "
            "VALUES ($1,$2,$3,$4,'{}'::json,'{}'::json,NULL,$5,$6)",
            revision_id,
            template_id,
            fingerprint_value,
            template_fingerprint,
            revoked,
            created_at,
        )
        return revision_id
    await connection.execute(
        "INSERT INTO environment_revisions "
        "(id,template_id,fingerprint,template_fingerprint,portable_fingerprint,"
        "configuration,runtime_identity,toolchain_identity,revoked,created_at) "
        "VALUES ($1,$2,$3,$4,$5,'{}'::json,'{}'::json,NULL,$6,$7)",
        revision_id,
        template_id,
        fingerprint_value,
        template_fingerprint,
        portable_fingerprint,
        revoked,
        created_at,
    )
    return revision_id


def test_fresh_upgrade_downgrade_and_reupgrade(migration_database):
    config, database = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(PORTABLE_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(SCAN_REVISION).down_revision == PORTABLE_REVISION
    assert script.get_revision(BATCH_REVISION).down_revision == SCAN_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == BATCH_REVISION

    command.upgrade(config, "head")
    command.upgrade(config, "head")
    upgraded = asyncio.run(schema_state(database))
    assert upgraded["revision"] == HEAD_REVISION
    portable_column = upgraded["columns"][PORTABLE_COLUMN]
    assert portable_column["is_nullable"] == "YES"
    assert portable_column["data_type"] == "character varying"
    assert portable_column["character_maximum_length"] == 64
    assert "(portable_fingerprint)" in upgraded["indexes"][PORTABLE_INDEX]
    assert "UNIQUE" not in upgraded["indexes"][PORTABLE_INDEX]
    assert "UNIQUE INDEX" in upgraded["indexes"][ACTIVE_FINGERPRINT_INDEX]
    assert "WHERE (revoked = false)" in upgraded["indexes"][ACTIVE_FINGERPRINT_INDEX]
    assert not any(
        "UNIQUE (template_id, fingerprint)" in definition
        for definition in upgraded["constraints"].values()
    )

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = asyncio.run(schema_state(database))
    assert downgraded["revision"] == PREVIOUS_REVISION
    assert PORTABLE_COLUMN not in downgraded["columns"]
    assert PORTABLE_INDEX not in downgraded["indexes"]
    assert ACTIVE_FINGERPRINT_INDEX not in downgraded["indexes"]
    assert any(
        "UNIQUE (template_id, fingerprint)" in definition
        for definition in downgraded["constraints"].values()
    )

    command.upgrade(config, "head")
    reupgraded = asyncio.run(schema_state(database))
    assert reupgraded["revision"] == HEAD_REVISION
    assert PORTABLE_COLUMN in reupgraded["columns"]
    assert ACTIVE_FINGERPRINT_INDEX in reupgraded["indexes"]
    assert PORTABLE_INDEX in reupgraded["indexes"]


def test_active_and_revoked_duplicate_fingerprints_are_allowed(migration_database):
    config, database = migration_database
    command.upgrade(config, "head")

    async def seed():
        connection = await connect(database)
        try:
            template_id = await insert_template(connection)
            fingerprint_value = "a" * 64
            active_id = await insert_revision(
                connection, template_id, fingerprint_value=fingerprint_value
            )
            revoked_id = await insert_revision(
                connection,
                template_id,
                fingerprint_value=fingerprint_value,
                revoked=True,
            )
            return active_id, revoked_id

        finally:
            await connection.close()

    active_id, revoked_id = asyncio.run(seed())
    state = asyncio.run(schema_state(database))
    assert state["revision_count"] == 2
    assert active_id != revoked_id


def test_two_active_duplicate_fingerprints_are_rejected(migration_database):
    config, database = migration_database
    command.upgrade(config, "head")

    async def seed():
        connection = await connect(database)
        try:
            template_id = await insert_template(connection)
            fingerprint_value = "a" * 64
            await insert_revision(connection, template_id, fingerprint_value=fingerprint_value)
            await insert_revision(connection, template_id, fingerprint_value=fingerprint_value)
        finally:
            await connection.close()

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        asyncio.run(seed())
    assert asyncio.run(schema_state(database))["revision_count"] == 1


def test_downgrade_preflight_rejects_duplicates_without_changing_the_schema(
    migration_database,
):
    config, database = migration_database
    command.upgrade(config, "head")

    async def seed():
        connection = await connect(database)
        try:
            template_id = await insert_template(connection)
            fingerprint_value = "a" * 64
            await insert_revision(connection, template_id, fingerprint_value=fingerprint_value)
            await insert_revision(
                connection,
                template_id,
                fingerprint_value=fingerprint_value,
                revoked=True,
            )
        finally:
            await connection.close()

    asyncio.run(seed())
    before = asyncio.run(schema_state(database))

    with pytest.raises(RuntimeError, match="duplicate rows"):
        command.downgrade(config, PREVIOUS_REVISION)

    after = asyncio.run(schema_state(database))
    assert after["revision"] == HEAD_REVISION
    assert after["columns"] == before["columns"]
    assert after["indexes"] == before["indexes"]
    assert after["constraints"] == before["constraints"]
    assert after["revision_count"] == 2


def test_upgrade_preserves_legacy_revisions_and_leaves_portable_identity_null(
    migration_database,
):
    config, database = migration_database
    command.upgrade(config, PREVIOUS_REVISION)

    async def seed():
        connection = await connect(database)
        try:
            template_id = await insert_template(connection)
            legacy_id = await insert_revision(
                connection,
                template_id,
                fingerprint_value="a" * 64,
                include_portable=False,
            )
            return legacy_id
        finally:
            await connection.close()

    legacy_id = asyncio.run(seed())
    command.upgrade(config, "head")

    async def verify():
        connection = await connect(database)
        try:
            row = await connection.fetchrow(
                "SELECT fingerprint, portable_fingerprint, revoked "
                "FROM environment_revisions WHERE id=$1",
                legacy_id,
            )
            return row
        finally:
            await connection.close()

    row = asyncio.run(verify())
    assert row["fingerprint"] == "a" * 64
    assert row["portable_fingerprint"] is None
    assert row["revoked"] is False
    assert asyncio.run(schema_state(database))["revision_count"] == 1
