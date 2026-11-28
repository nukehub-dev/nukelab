# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Rehearse additive workflow schema on disposable PostgreSQL databases."""

import asyncio
import uuid
from pathlib import Path

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import settings
from app.db.base import Base

PREVIOUS_REVISION = "34ce1a62ffe8"
BATCH_REVISION = "b7d4e1c9a2f5"
ADMISSION_REVISION = "e2c7a9f4d6b1"
HEAD_REVISION = "a3b8c1d4e5f6"
NEW_TABLES = {
    "environment_revisions",
    "server_launch_records",
    "volume_operations",
    "server_launch_intents",
    "server_launch_operations",
    "volume_restores",
    "batch_jobs",
    "batch_job_logs",
    "credit_holds",
}


async def admin_connection():
    return await asyncpg.connect(
        host="postgres", user="nukelab", password="nukelab123", database="nukelab"
    )


@pytest.fixture
def migration_database(monkeypatch):
    # UUID-generated identifier, never a configured application database.
    name = "migration_test_" + uuid.uuid4().hex

    async def create():
        connection = await admin_connection()
        try:
            await connection.execute(f'CREATE DATABASE "{name}"')
        finally:
            await connection.close()

    async def drop():
        connection = await admin_connection()
        try:
            await connection.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        finally:
            await connection.close()

    asyncio.run(create())
    monkeypatch.setattr(
        settings, "database_url", f"postgresql+asyncpg://nukelab:nukelab123@postgres/{name}"
    )
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).parents[2] / "alembic"))
    try:
        yield config, name
    finally:
        asyncio.run(drop())


async def connect(name):
    return await asyncpg.connect(
        host="postgres", user="nukelab", password="nukelab123", database=name
    )


async def tables(name):
    connection = await connect(name)
    try:
        return set(
            await connection.fetchval(
                "SELECT array_agg(tablename) FROM pg_tables WHERE schemaname='public'"
            )
        )
    finally:
        await connection.close()


async def _plan_availability(name):
    connection = await connect(name)
    try:
        return await connection.fetchrow(
            "SELECT allow_servers, allow_batch_jobs FROM server_plans WHERE slug = 'legacy-plan'"
        )
    finally:
        await connection.close()


async def _plan_columns(name):
    connection = await connect(name)
    try:
        rows = await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'server_plans'"
        )
        return {row["column_name"] for row in rows}
    finally:
        await connection.close()


def test_plan_availability_backfill_and_downgrade(migration_database):
    config, database = migration_database
    command.upgrade(config, "f1a2b3c4d5e6")

    async def insert_legacy_plan():
        connection = await connect(database)
        try:
            await connection.execute(
                "INSERT INTO server_plans (id, name, slug) VALUES ($1, $2, $3)",
                uuid.uuid4(),
                "Legacy Plan",
                "legacy-plan",
            )
        finally:
            await connection.close()

    asyncio.run(insert_legacy_plan())
    command.upgrade(config, "head")
    row = asyncio.run(_plan_availability(database))
    assert row["allow_servers"] is True
    assert row["allow_batch_jobs"] is True

    command.downgrade(config, "f1a2b3c4d5e6")
    assert "allow_servers" not in asyncio.run(_plan_columns(database))
    assert "allow_batch_jobs" not in asyncio.run(_plan_columns(database))


def test_fresh_upgrade_downgrade_and_reupgrade(migration_database):
    config, name = migration_database
    assert ScriptDirectory.from_config(config).get_heads() == [HEAD_REVISION]
    command.upgrade(config, "head")
    assert NEW_TABLES <= asyncio.run(tables(name))
    # The first downgrade removes only the paid billing journal.
    command.downgrade(config, ADMISSION_REVISION)
    after_billing = asyncio.run(tables(name))
    assert "credit_holds" not in after_billing
    assert NEW_TABLES - {"credit_holds"} <= after_billing
    # The next downgrade removes only the admission reservation columns.
    command.downgrade(config, BATCH_REVISION)
    after_admission = asyncio.run(tables(name))
    assert "batch_jobs" in after_admission
    # The next downgrade removes the additive batch tables.
    command.downgrade(config, "-1")
    after_batch = asyncio.run(tables(name))
    assert "batch_jobs" not in after_batch
    assert "batch_job_logs" not in after_batch
    assert (
        NEW_TABLES
        - {
            "batch_jobs",
            "batch_job_logs",
            "credit_holds",
        }
        <= after_batch
    )
    # Four more steps reach the pre-workflow baseline used by this rehearsal.
    command.downgrade(config, "-1")
    command.downgrade(config, "-1")
    command.downgrade(config, "-1")
    command.downgrade(config, "-1")
    assert "volume_restores" not in asyncio.run(tables(name))
    assert NEW_TABLES - {
        "volume_restores",
        "batch_jobs",
        "batch_job_logs",
        "credit_holds",
    } <= asyncio.run(tables(name))
    command.upgrade(config, "head")
    command.downgrade(config, PREVIOUS_REVISION)
    assert NEW_TABLES.isdisjoint(asyncio.run(tables(name)))
    command.upgrade(config, "head")
    assert NEW_TABLES <= asyncio.run(tables(name))


def test_upgrade_preserves_legacy_rows_without_inventing_payload(migration_database):
    config, name = migration_database
    command.upgrade(config, PREVIOUS_REVISION)
    owner, plan, environment, queue, backup = [uuid.uuid4() for _ in range(5)]

    async def seed():
        connection = await connect(name)
        try:
            await connection.execute(
                "INSERT INTO users (id,username,email,role,profile_visibility,credit_requests_blocked) VALUES ($1,'legacy','legacy@example.test','user','private',false)",
                owner,
            )
            await connection.execute(
                "INSERT INTO server_plans (id,name,slug) VALUES ($1,'legacy','legacy')", plan
            )
            await connection.execute(
                "INSERT INTO environment_templates (id,name,slug,image) VALUES ($1,'legacy','legacy','legacy:tag')",
                environment,
            )
            await connection.execute(
                "INSERT INTO server_queue (id,user_id,environment_id,plan_id,status,server_name) VALUES ($1,$2,$3,$4,'pending','legacy')",
                queue,
                owner,
                environment,
                plan,
            )
            await connection.execute(
                "INSERT INTO volume_backups (id,user_id,volume_name,status) VALUES ($1,$2,'legacy','pending')",
                backup,
                owner,
            )
        finally:
            await connection.close()

    async def verify():
        connection = await connect(name)
        try:
            row = await connection.fetchrow("SELECT * FROM server_queue WHERE id=$1", queue)
            assert row["request_payload"] is None and row["request_version"] is None
            assert row["requested_gpu"] == 0
            saved = await connection.fetchrow("SELECT * FROM volume_backups WHERE id=$1", backup)
            assert saved["reserved_bytes"] == 0
            assert saved["format_version"] is None
            assert saved["sha256"] is None
            assert saved["source_volume_id"] is None
        finally:
            await connection.close()

    asyncio.run(seed())
    command.upgrade(config, "head")
    asyncio.run(verify())
    command.downgrade(config, PREVIOUS_REVISION)


def test_upgrade_after_auto_create_tables(migration_database):
    config, name = migration_database
    command.upgrade(config, PREVIOUS_REVISION)

    async def create_models():
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(create_models())
    command.upgrade(config, "head")
    assert NEW_TABLES <= asyncio.run(tables(name))
    command.downgrade(config, PREVIOUS_REVISION)
