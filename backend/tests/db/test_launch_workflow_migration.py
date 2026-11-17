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
WORKFLOW_REVISION = "e1840b2c6a39"
NEW_TABLES = {
    "environment_revisions",
    "server_launch_records",
    "volume_operations",
    "server_launch_intents",
    "server_launch_operations",
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


def test_fresh_upgrade_downgrade_and_reupgrade(migration_database):
    config, name = migration_database
    assert ScriptDirectory.from_config(config).get_heads() == [WORKFLOW_REVISION]
    command.upgrade(config, "head")
    assert NEW_TABLES <= asyncio.run(tables(name))
    command.downgrade(config, "-1")
    assert "server_launch_operations" not in asyncio.run(tables(name))
    assert NEW_TABLES - {"server_launch_operations"} <= asyncio.run(tables(name))
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
            assert (
                await connection.fetchval("SELECT count(*) FROM volume_backups WHERE id=$1", backup)
                == 1
            )
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
