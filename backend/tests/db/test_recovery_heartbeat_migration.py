# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Rehearse recovery executor schema on disposable PostgreSQL databases."""

import asyncio
import uuid
from datetime import datetime

from alembic.script import ScriptDirectory

from alembic import command
from tests.db.test_launch_workflow_migration import connect
from tests.db.test_launch_workflow_migration import migration_database as migration_database

PREVIOUS_REVISION = "f6b29a41d7c8"
RECOVERY_REVISION = "b1e7c4a9d2f6"
HEAD_REVISION = "c5f8a2d91e47"
OPERATION_TABLES = ("server_launch_operations", "volume_backups", "volume_restores")
ALL_TABLES = ("worker_heartbeats", *OPERATION_TABLES)

HEARTBEAT_COLUMNS = {
    "executor_id": ("NO", "uuid", None),
    "hostname": ("NO", "character varying", 255),
    "container_id": ("YES", "character varying", 255),
    "container_started_at": ("YES", "character varying", 64),
    "pid": ("NO", "integer", None),
    "process_start_time": ("YES", "character varying", 64),
    "single_process_container": ("NO", "boolean", None),
    "schema_version": ("NO", "character varying", 32),
    "state": ("NO", "character varying", 16),
    "heartbeat_at": ("NO", "timestamp without time zone", None),
    "created_at": ("NO", "timestamp without time zone", None),
    "updated_at": ("NO", "timestamp without time zone", None),
}
OPERATION_COLUMNS = {
    "executor_id": ("YES", "uuid", None),
    "heartbeat_at": ("YES", "timestamp without time zone", None),
}


async def snapshot(database):
    connection = await connect(database)
    try:
        revision = await connection.fetchval("SELECT version_num FROM alembic_version")
        worker_table = await connection.fetchval(
            "SELECT to_regclass('public.worker_heartbeats') IS NOT NULL"
        )
        columns = {}
        for row in await connection.fetch(
            "SELECT table_name, column_name, is_nullable, data_type, character_maximum_length "
            "FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name = ANY($1::text[])",
            list(ALL_TABLES),
        ):
            columns.setdefault(row["table_name"], {})[row["column_name"]] = row
        indexes = {}
        for row in await connection.fetch(
            "SELECT tablename, indexname, indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND tablename = ANY($1::text[])",
            list(ALL_TABLES),
        ):
            indexes.setdefault(row["tablename"], {})[row["indexname"]] = row["indexdef"]
        primary_key = []
        if worker_table:
            primary_key = [
                row["column_name"]
                for row in await connection.fetch(
                    "SELECT kcu.column_name FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "ON tc.constraint_name = kcu.constraint_name "
                    "AND tc.constraint_schema = kcu.constraint_schema "
                    "WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema='public' "
                    "AND tc.table_name='worker_heartbeats' ORDER BY kcu.ordinal_position"
                )
            ]
        executor_foreign_keys = {
            table: await connection.fetchval(
                "SELECT count(*) FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "AND tc.constraint_schema = kcu.constraint_schema "
                "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public' "
                "AND tc.table_name=$1 AND kcu.column_name='executor_id'",
                table,
            )
            for table in OPERATION_TABLES
        }
        return {
            "revision": revision,
            "worker_table": worker_table,
            "columns": columns,
            "indexes": indexes,
            "primary_key": primary_key,
            "executor_foreign_keys": executor_foreign_keys,
        }
    finally:
        await connection.close()


def assert_columns(actual, expected):
    for name, (nullable, data_type, maximum_length) in expected.items():
        column = actual[name]
        assert column["is_nullable"] == nullable
        assert column["data_type"] == data_type
        assert column["character_maximum_length"] == maximum_length


def test_recovery_schema_upgrade_downgrade_reupgrade(migration_database):
    config, database = migration_database
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == [HEAD_REVISION]
    assert script.get_revision(RECOVERY_REVISION).down_revision == PREVIOUS_REVISION
    assert script.get_revision(HEAD_REVISION).down_revision == RECOVERY_REVISION

    command.upgrade(config, "head")
    upgraded = asyncio.run(snapshot(database))
    assert upgraded["revision"] == HEAD_REVISION
    assert upgraded["worker_table"] is True
    assert upgraded["primary_key"] == ["executor_id"]
    assert set(upgraded["columns"]["worker_heartbeats"]) == set(HEARTBEAT_COLUMNS)
    assert_columns(upgraded["columns"]["worker_heartbeats"], HEARTBEAT_COLUMNS)
    heartbeat_index = upgraded["indexes"]["worker_heartbeats"][
        "ix_worker_heartbeats_state_heartbeat_at"
    ]
    assert "(state, heartbeat_at)" in heartbeat_index
    for table in OPERATION_TABLES:
        assert_columns(upgraded["columns"][table], OPERATION_COLUMNS)
        assert upgraded["executor_foreign_keys"][table] == 0
        assert f"ix_{table}_executor_id" in upgraded["indexes"][table]
        assert "(executor_id)" in upgraded["indexes"][table][f"ix_{table}_executor_id"]

    command.downgrade(config, PREVIOUS_REVISION)
    downgraded = asyncio.run(snapshot(database))
    assert downgraded["revision"] == PREVIOUS_REVISION
    assert downgraded["worker_table"] is False
    assert "worker_heartbeats" not in downgraded["columns"]
    for table in OPERATION_TABLES:
        assert "executor_id" not in downgraded["columns"][table]
        assert "heartbeat_at" not in downgraded["columns"][table]
        assert f"ix_{table}_executor_id" not in downgraded["indexes"].get(table, {})

    command.upgrade(config, "head")
    reupgraded = asyncio.run(snapshot(database))
    assert reupgraded["revision"] == HEAD_REVISION
    assert reupgraded["worker_table"] is True
    assert reupgraded["primary_key"] == ["executor_id"]
    for table in OPERATION_TABLES:
        assert_columns(reupgraded["columns"][table], OPERATION_COLUMNS)
        assert f"ix_{table}_executor_id" in reupgraded["indexes"][table]


async def seed_legacy_rows(database):
    connection = await connect(database)
    try:
        owner, server, operation, backup, restore = [uuid.uuid4() for _ in range(5)]
        created = datetime(2026, 11, 1, 12)
        await connection.execute(
            "INSERT INTO users (id,username,email,role,profile_visibility,credit_requests_blocked) "
            "VALUES ($1,'legacy-heartbeat','legacy-heartbeat@example.test','user','private',false)",
            owner,
        )
        await connection.execute(
            "INSERT INTO servers (id,user_id,name,status) "
            "VALUES ($1,$2,'legacy-heartbeat','running')",
            server,
            owner,
        )
        await connection.execute(
            "INSERT INTO server_launch_operations "
            "(id,server_id,owner_id,action,state,fencing_token,mounts,previous_mounts,"
            "gpu_devices,username,resources,created_at,updated_at) "
            "VALUES ($1,$2,$3,'start','executing',$4,'[]'::jsonb,'[]'::jsonb,'[]'::jsonb,"
            "'legacy','{\"cpu\": 1}'::jsonb,$5,$5)",
            operation,
            server,
            owner,
            uuid.uuid4(),
            created,
        )
        await connection.execute(
            "INSERT INTO volume_backups (id,user_id,volume_name,status,created_at) "
            "VALUES ($1,$2,'legacy-heartbeat','in_progress',$3)",
            backup,
            owner,
            created,
        )
        await connection.execute(
            "INSERT INTO volume_restores "
            "(id,backup_id,user_id,destination_name,display_name,max_size_bytes,status,"
            "fencing_token,created_at) "
            "VALUES ($1,$2,$3,'legacy-heartbeat','Legacy heartbeat restore',1048576,"
            "'restoring',$4,$5)",
            restore,
            backup,
            owner,
            uuid.uuid4(),
            created,
        )
        return {
            "server_launch_operations": operation,
            "volume_backups": backup,
            "volume_restores": restore,
        }
    finally:
        await connection.close()


async def assert_legacy_rows(database, identifiers, *, columns_present):
    connection = await connect(database)
    try:
        for table, identifier in identifiers.items():
            row = await connection.fetchrow(f"SELECT * FROM {table} WHERE id=$1", identifier)
            assert row is not None
            if columns_present:
                assert row["executor_id"] is None
                assert row["heartbeat_at"] is None
            else:
                assert "executor_id" not in row
                assert "heartbeat_at" not in row
        assert await connection.fetchval("SELECT count(*) FROM server_launch_operations") == 1
        assert await connection.fetchval("SELECT count(*) FROM volume_backups") == 1
        assert await connection.fetchval("SELECT count(*) FROM volume_restores") == 1
        if columns_present:
            assert await connection.fetchval("SELECT count(*) FROM worker_heartbeats") == 0
    finally:
        await connection.close()


def test_upgrade_preserves_legacy_operation_rows(migration_database):
    config, database = migration_database
    command.upgrade(config, PREVIOUS_REVISION)
    identifiers = asyncio.run(seed_legacy_rows(database))
    command.upgrade(config, "head")
    asyncio.run(assert_legacy_rows(database, identifiers, columns_present=True))
    command.downgrade(config, PREVIOUS_REVISION)
    asyncio.run(assert_legacy_rows(database, identifiers, columns_present=False))
