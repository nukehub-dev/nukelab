# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Runtime observations must not invalidate newer lifecycle reservations."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update

from app.api.servers import _observe_server_runtime
from app.models.server import Server
from app.services.server_operation_service import create_operation


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["starting", "stopping"])
async def test_reserved_status_is_never_probed_or_overwritten(
    db_session, test_user, monkeypatch, status
):
    server = Server(name="reserved", user_id=test_user.id, status=status, container_id="runtime")
    db_session.add(server)
    await db_session.commit()
    probe = AsyncMock(return_value="stopped")
    monkeypatch.setattr("app.api.servers.spawner.get_status", probe)
    await _observe_server_runtime(server, db_session)
    assert server.status == status
    probe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["generation", "operation", "container"])
async def test_late_observation_cannot_overwrite_newer_runtime_authority(
    db_session, test_user, monkeypatch, change
):
    server = Server(name="observed", user_id=test_user.id, status="running", container_id="runtime")
    db_session.add(server)
    await db_session.commit()
    server_id = server.id
    old_version = server.updated_at

    async def probe(_):
        # Interleave another accepted lifecycle mutation while the network probe is in flight.
        if change == "operation":
            await create_operation(
                db_session,
                server_id=server_id,
                owner_id=test_user.id,
                action="restart",
                username=test_user.username,
                resources={"cpu": 1, "memory": "1g", "disk": "1g", "gpu": 0},
            )
        else:
            values = {"updated_at": old_version + timedelta(seconds=1)}
            if change == "container":
                values["container_id"] = "replacement"
            await db_session.execute(update(Server).where(Server.id == server_id).values(**values))
        await db_session.commit()
        return "stopped"

    monkeypatch.setattr("app.api.servers.spawner.get_status", probe)
    await _observe_server_runtime(server, db_session)
    assert server.status == "running"
    assert server.stopped_at is None


@pytest.mark.asyncio
async def test_probe_failure_keeps_loaded_rows_and_status(db_session, test_user, monkeypatch):
    rows = [
        Server(name=f"probe-{i}", user_id=test_user.id, status="running", container_id=str(i))
        for i in range(2)
    ]
    db_session.add_all(rows)
    await db_session.commit()
    monkeypatch.setattr(
        "app.api.servers.spawner.get_status", AsyncMock(side_effect=RuntimeError("offline"))
    )
    for row in rows:
        await _observe_server_runtime(row, db_session)
    assert [row.status for row in rows] == ["running", "running"]


@pytest.mark.asyncio
async def test_database_failure_is_not_swallowed_as_an_observation(
    db_session, test_user, monkeypatch
):
    server = Server(
        name="database-failure",
        user_id=test_user.id,
        status="running",
        container_id="runtime",
    )
    db_session.add(server)
    await db_session.commit()

    async def unavailable(_db):
        raise RuntimeError("admission database unavailable")

    monkeypatch.setattr("app.api.servers.spawner.get_status", AsyncMock(return_value="stopped"))
    monkeypatch.setattr("app.services.admission_service.acquire_admission_lock", unavailable)
    with pytest.raises(RuntimeError, match="admission database unavailable"):
        await _observe_server_runtime(server, db_session)
    assert server.status == "running" and server.stopped_at is None


@pytest.mark.asyncio
async def test_paused_runtime_keeps_memory_and_compute_accounting(
    db_session, test_user, monkeypatch
):
    from app.services.resource_pool_service import ResourcePoolService

    server = Server(
        name="paused",
        user_id=test_user.id,
        status="running",
        container_id="runtime",
        allocated_cpu=2,
        allocated_memory="4g",
    )
    db_session.add(server)
    await db_session.commit()
    monkeypatch.setattr("app.api.servers.spawner.get_status", AsyncMock(return_value="paused"))
    await _observe_server_runtime(server, db_session)
    assert server.status == "running" and server.stopped_at is None
    pool = await ResourcePoolService(db_session).get_available_resources()
    assert pool["cpu"]["allocated"] >= 2
    assert pool["memory_mb"]["allocated"] >= 4096
