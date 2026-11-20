# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Data-preserving operation-journal upgrade rehearsals on disposable databases."""

import asyncio
import json
import uuid
from datetime import datetime

import pytest

from alembic import command
from tests.db.test_launch_workflow_migration import connect
from tests.db.test_launch_workflow_migration import migration_database as migration_database

PREVIOUS = "d731a8f4c092"
TARGET = "e1840b2c6a39"
CREATED = datetime(2026, 11, 1, 12)


async def seed_base(connection):
    owner, plan, environment, revision = [uuid.uuid4() for _ in range(4)]
    await connection.execute(
        "INSERT INTO users (id,username,email,role,profile_visibility,credit_requests_blocked) "
        "VALUES ($1,'history','history@example.test','user','private',false)",
        owner,
    )
    await connection.execute(
        "INSERT INTO server_plans (id,name,slug) VALUES ($1,'history','history')", plan
    )
    await connection.execute(
        "INSERT INTO environment_templates (id,name,slug,image) VALUES ($1,'history','history','approved:tag')",
        environment,
    )
    identity = {
        "requested_reference": "approved:tag",
        "local_id": "sha256:" + "a" * 64,
        "repository_digests": [],
        "os": "linux",
        "architecture": "amd64",
        "registry_verified": False,
    }
    await connection.execute(
        "INSERT INTO environment_revisions (id,template_id,fingerprint,template_fingerprint,configuration,runtime_identity,revoked,created_at) "
        "VALUES ($1,$2,$3,$4,$5::json,$6::json,false,$7)",
        revision,
        environment,
        "a" * 64,
        "b" * 64,
        json.dumps({"image": "approved:tag"}),
        json.dumps(identity),
        CREATED,
    )
    return {
        "owner": owner,
        "plan": plan,
        "environment": environment,
        "revision": revision,
        "identity": identity,
    }


async def seed_server(connection, base, *, name="history-server", status="running"):
    identifier = uuid.uuid4()
    await connection.execute(
        "INSERT INTO servers (id,user_id,name,status,plan_id,environment_id,container_id,allocated_cpu,allocated_memory,allocated_disk,allocated_gpu) "
        "VALUES ($1,$2,$3,$4,$5,$6,'exact-runtime',2.5,'3072m','8g',1)",
        identifier,
        base["owner"],
        name,
        status,
        base["plan"],
        base["environment"],
    )
    return identifier


def payload(base, name="history-server"):
    return {
        "name": name,
        "plan_id": str(base["plan"]),
        "environment_id": str(base["environment"]),
        "volume_mounts": [
            {
                "volume_id": "",
                "mount_path": "/home/history",
                "mode": "read_only",
                "max_size_bytes": 1048576,
                "is_primary": True,
            }
        ],
    }


async def seed_intent(connection, base, server_id):
    mounts = [
        {
            "volume_id": str(uuid.uuid4()),
            "volume_name": "exact-private-data",
            "mount_path": "/home/history",
            "mode": "read_only",
            "is_primary": True,
            "auto_created": False,
            "max_size_bytes": 1048576,
        }
    ]
    await connection.execute(
        "INSERT INTO server_launch_intents (server_id,owner_id,revision_id,request_payload,mounts,gpu_devices,environment_slug,username,created_at) "
        "VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6::jsonb,'history','history',$7)",
        server_id,
        base["owner"],
        base["revision"],
        json.dumps(payload(base)),
        json.dumps(mounts),
        json.dumps(["nvidia.com/gpu=0"]),
        CREATED,
    )
    return mounts


async def seed_record(connection, base, server_id, *, recorded_server=None):
    await connection.execute(
        "INSERT INTO server_launch_records (id,server_id,user_id,revision_id,generation,manifest,actual_runtime_identity,created_at) "
        "VALUES ($1,$2,$3,$4,1,$5::json,$6::json,$7)",
        server_id,
        recorded_server or server_id,
        base["owner"],
        base["revision"],
        json.dumps({"schema_version": "nukelab.environment/v1"}),
        json.dumps(base["identity"]),
        CREATED,
    )


async def seed_queue(connection, base, *, name="waiting", status="pending", valid_payload=False):
    identifier = uuid.uuid4()
    await connection.execute(
        "INSERT INTO server_queue (id,user_id,environment_id,plan_id,status,server_name,request_version,request_payload) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
        identifier,
        base["owner"],
        base["environment"],
        base["plan"],
        status,
        name,
        1 if valid_payload else None,
        json.dumps(payload(base, name)) if valid_payload else None,
    )
    return identifier


@pytest.mark.parametrize(
    "status,recorded",
    [
        ("running", True),
        ("stopped", True),
        ("starting", True),
        ("running", False),
        ("stopped", False),
        ("error", False),
    ],
)
def test_intent_backfill_requires_historical_completion_proof(migration_database, status, recorded):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            server_id = await seed_server(connection, base, status=status)
            mounts = await seed_intent(connection, base, server_id)
            if recorded:
                await seed_record(connection, base, server_id)
            return base, server_id, mounts
        finally:
            await connection.close()

    base, server_id, mounts = asyncio.run(seed())
    command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            operation = await connection.fetchrow(
                "SELECT * FROM server_launch_operations WHERE id=$1", server_id
            )
            old_intent = await connection.fetchrow(
                "SELECT * FROM server_launch_intents WHERE server_id=$1", server_id
            )
            server = await connection.fetchrow("SELECT * FROM servers WHERE id=$1", server_id)
            complete = recorded and status in ("running", "stopped")
            assert operation["state"] == ("succeeded" if complete else "uncertain")
            assert operation["reason_code"] == (None if complete else "recovery_required")
            assert server["status"] == (status if complete else "starting")
            if not complete:
                assert server["status_reason"] == "recovery_required"
            assert operation["fencing_token"] is not None
            assert operation["revision_id"] == old_intent["revision_id"] == base["revision"]
            assert (
                json.loads(operation["request_payload"])
                == json.loads(old_intent["request_payload"])
                == payload(base)
            )
            assert json.loads(operation["mounts"]) == mounts
            assert json.loads(operation["previous_mounts"]) == []
            assert json.loads(operation["gpu_devices"]) == ["nvidia.com/gpu=0"]
            assert json.loads(operation["resources"]) == {
                "cpu": 2.5,
                "memory": "3072m",
                "disk": "8g",
                "gpu": 1,
            }
            assert operation["generation"] == 1 and operation["created_at"] == CREATED
            assert (operation["finished_at"] is not None) == complete
            assert await connection.fetchval(
                "SELECT count(*) FROM server_launch_records WHERE id=$1", server_id
            ) == int(recorded)
        finally:
            await connection.close()

    asyncio.run(verify())


def test_unrecoverable_pending_queue_is_cancelled_without_inventing_configuration(
    migration_database,
):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            return await seed_queue(connection, base)
        finally:
            await connection.close()

    identifier = asyncio.run(seed())
    command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            row = await connection.fetchrow("SELECT * FROM server_queue WHERE id=$1", identifier)
            assert row["status"] == "cancelled" and row["reason_code"] == "configuration_changed"
            assert row["request_payload"] is row["request_version"] is None
            assert "Submit a new request" in row["error_message"]
            assert row["server_id"] is None
        finally:
            await connection.close()

    asyncio.run(verify())


@pytest.mark.parametrize("conflict", ["server_names", "queue_names", "server_queue_overlap"])
def test_name_conflicts_abort_atomically_without_deleting_user_records(
    migration_database, conflict
):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            pending = await seed_queue(connection, base, name="unrecoverable")
            if conflict == "server_names":
                await seed_server(connection, base, name="conflict")
                await seed_server(connection, base, name="conflict")
            elif conflict == "queue_names":
                await seed_queue(connection, base, name="conflict", valid_payload=True)
                await seed_queue(connection, base, name="conflict", valid_payload=True)
            else:
                await seed_server(connection, base, name="conflict")
                await seed_queue(connection, base, name="conflict", valid_payload=True)
            return pending
        finally:
            await connection.close()

    pending = asyncio.run(seed())
    with pytest.raises(RuntimeError, match="conflicting server/queue names"):
        command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == PREVIOUS
            assert (
                await connection.fetchval("SELECT to_regclass('public.server_launch_operations')")
                is None
            )
            assert await connection.fetchval(
                "SELECT count(*) FROM servers WHERE name='conflict'"
            ) == (
                2 if conflict == "server_names" else 1 if conflict == "server_queue_overlap" else 0
            )
            assert await connection.fetchval(
                "SELECT count(*) FROM server_queue WHERE server_name='conflict'"
            ) == (
                2 if conflict == "queue_names" else 1 if conflict == "server_queue_overlap" else 0
            )
            # Even the earlier safe cancellation is rolled back on failed upgrade.
            row = await connection.fetchrow(
                "SELECT status,request_payload,reason_code FROM server_queue WHERE id=$1", pending
            )
            assert (
                row["status"] == "pending" and row["request_payload"] is row["reason_code"] is None
            )
        finally:
            await connection.close()

    asyncio.run(verify())


def test_unidentified_starting_queue_requires_reconciliation_before_upgrade(migration_database):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            return await seed_queue(connection, base, status="starting")
        finally:
            await connection.close()

    identifier = asyncio.run(seed())
    with pytest.raises(RuntimeError, match="Reconcile legacy starting queue"):
        command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            row = await connection.fetchrow("SELECT * FROM server_queue WHERE id=$1", identifier)
            assert row["status"] == "starting" and row["server_id"] is None
            assert row["request_payload"] is None
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == PREVIOUS
        finally:
            await connection.close()

    asyncio.run(verify())


def test_mismatched_historical_record_cannot_establish_completed_operation(migration_database):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            server_id = await seed_server(connection, base)
            other_server = await seed_server(connection, base, name="different-server")
            await seed_intent(connection, base, server_id)
            await seed_record(connection, base, server_id, recorded_server=other_server)
            return server_id, other_server
        finally:
            await connection.close()

    server_id, other_server = asyncio.run(seed())
    command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            assert (
                await connection.fetchval(
                    "SELECT state FROM server_launch_operations WHERE id=$1", server_id
                )
                == "uncertain"
            )
            assert (
                await connection.fetchval(
                    "SELECT server_id FROM server_launch_records WHERE id=$1", server_id
                )
                == other_server
            )
            assert (
                await connection.fetchval("SELECT status FROM servers WHERE id=$1", server_id)
                == "starting"
            )
        finally:
            await connection.close()

    asyncio.run(verify())


def test_incomplete_old_resource_reservation_aborts_without_fabricating_capacity(
    migration_database,
):
    config, database = migration_database
    command.upgrade(config, PREVIOUS)

    async def seed():
        connection = await connect(database)
        try:
            base = await seed_base(connection)
            identifier = await seed_server(connection, base)
            await seed_intent(connection, base, identifier)
            await connection.execute(
                "UPDATE servers SET allocated_cpu=NULL WHERE id=$1", identifier
            )
            return identifier
        finally:
            await connection.close()

    identifier = asyncio.run(seed())
    with pytest.raises(RuntimeError, match="incomplete launch resource reservations"):
        command.upgrade(config, TARGET)

    async def verify():
        connection = await connect(database)
        try:
            row = await connection.fetchrow(
                "SELECT status,allocated_cpu FROM servers WHERE id=$1", identifier
            )
            assert row["status"] == "running" and row["allocated_cpu"] is None
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == PREVIOUS
            assert (
                await connection.fetchval("SELECT to_regclass('public.server_launch_operations')")
                is None
            )
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM server_launch_intents WHERE server_id=$1", identifier
                )
                == 1
            )
        finally:
            await connection.close()

    asyncio.run(verify())
