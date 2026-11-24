# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Worker heartbeat registry and operation executor identity invariants."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.volume_backup import VolumeBackup
from app.models.volume_restore import VolumeRestore
from app.models.worker_heartbeat import WorkerHeartbeat

OPERATION_MODELS = [ServerLaunchOperation, VolumeBackup, VolumeRestore]


def test_worker_heartbeat_columns_match_frozen_schema():
    columns = WorkerHeartbeat.__table__.columns

    assert columns["executor_id"].primary_key is True
    assert columns["executor_id"].nullable is False
    assert isinstance(columns["executor_id"].type, UUID)
    assert columns["hostname"].nullable is False
    assert isinstance(columns["hostname"].type, String)
    assert columns["hostname"].type.length == 255
    assert columns["container_id"].nullable is True
    assert isinstance(columns["container_id"].type, String)
    assert columns["container_id"].type.length == 255
    assert columns["container_started_at"].nullable is True
    assert isinstance(columns["container_started_at"].type, String)
    assert columns["container_started_at"].type.length == 64
    assert columns["pid"].nullable is False
    assert isinstance(columns["pid"].type, Integer)
    assert columns["process_start_time"].nullable is True
    assert isinstance(columns["process_start_time"].type, String)
    assert columns["process_start_time"].type.length == 64
    assert columns["single_process_container"].nullable is False
    assert isinstance(columns["single_process_container"].type, Boolean)
    assert columns["schema_version"].nullable is False
    assert isinstance(columns["schema_version"].type, String)
    assert columns["schema_version"].type.length == 32
    assert columns["state"].nullable is False
    assert isinstance(columns["state"].type, String)
    assert columns["state"].type.length == 16
    assert columns["heartbeat_at"].nullable is False
    assert isinstance(columns["heartbeat_at"].type, DateTime)
    assert columns["created_at"].nullable is False
    assert isinstance(columns["created_at"].type, DateTime)
    assert columns["updated_at"].nullable is False
    assert isinstance(columns["updated_at"].type, DateTime)

    indexes = {index.name: index for index in WorkerHeartbeat.__table__.indexes}
    index = indexes["ix_worker_heartbeats_state_heartbeat_at"]
    assert [column.name for column in index.columns] == ["state", "heartbeat_at"]
    assert index.unique is False


@pytest.mark.asyncio
async def test_worker_heartbeat_defaults_and_mutation(db_session):
    before = utc_now()
    beat = WorkerHeartbeat(hostname="worker-1", pid=4242, schema_version="nukelab-journal/v1")
    db_session.add(beat)
    await db_session.flush()
    await db_session.refresh(beat)

    assert isinstance(beat.executor_id, uuid.UUID)
    assert beat.container_id is None
    assert beat.process_start_time is None
    assert beat.single_process_container is False
    assert beat.state == "running"
    assert beat.heartbeat_at >= before
    assert beat.created_at >= before
    assert beat.updated_at >= before

    created_at = beat.created_at
    beat.updated_at = datetime(2000, 1, 1)
    await db_session.flush()
    beat.state = "stopped"
    beat.heartbeat_at = utc_now()
    await db_session.flush()
    await db_session.refresh(beat)

    assert beat.state == "stopped"
    assert beat.created_at == created_at
    assert beat.updated_at > datetime(2000, 1, 1)


@pytest.mark.parametrize("model", OPERATION_MODELS)
def test_operation_models_expose_nullable_executor_tracking(model):
    columns = model.__table__.columns

    assert columns["executor_id"].nullable is True
    assert isinstance(columns["executor_id"].type, UUID)
    assert not columns["executor_id"].foreign_keys
    assert columns["heartbeat_at"].nullable is True
    assert isinstance(columns["heartbeat_at"].type, DateTime)

    indexes = {index.name: index for index in model.__table__.indexes}
    index = indexes[f"ix_{model.__tablename__}_executor_id"]
    assert [column.name for column in index.columns] == ["executor_id"]


@pytest.mark.asyncio
async def test_launch_operation_guard_permits_heartbeat_updates_only(db_session, test_user):
    server = Server(
        id=uuid.uuid4(),
        name="heartbeat-" + uuid.uuid4().hex,
        user_id=test_user.id,
        status="starting",
    )
    db_session.add(server)
    await db_session.flush()
    operation = ServerLaunchOperation(
        server_id=server.id,
        owner_id=test_user.id,
        action="start",
        username=test_user.username,
        mounts=[],
        previous_mounts=[],
        gpu_devices=[],
        resources={"cpu": 1.0, "memory": "1g", "disk": "2g", "gpu": 0},
    )
    db_session.add(operation)
    await db_session.flush()

    executor_id = uuid.uuid4()
    claimed_at = utc_now()
    operation.executor_id = executor_id
    operation.heartbeat_at = claimed_at
    operation.state = "executing"
    await db_session.flush()
    await db_session.refresh(operation)

    assert operation.executor_id == executor_id
    assert operation.heartbeat_at == claimed_at
    assert operation.state == "executing"

    refreshed_at = utc_now()
    operation.heartbeat_at = refreshed_at
    await db_session.flush()
    await db_session.refresh(operation)
    assert operation.heartbeat_at == refreshed_at

    with pytest.raises(ValueError, match="immutable"):
        async with db_session.begin_nested():
            operation.action = "delete"
            await db_session.flush()
    await db_session.refresh(operation)
    assert operation.action == "start"
