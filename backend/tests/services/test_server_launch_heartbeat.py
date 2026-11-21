# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Launch provisioning refreshes the fenced heartbeat across runtime I/O."""

import asyncio
import contextlib
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.services import worker_heartbeat as heartbeat_module
from app.services.server_launch_service import (
    LaunchError,
    LaunchReservation,
    ServerLaunchService,
)
from tests.conftest import test_engine
from tests.services.test_server_launch_service import (
    IMAGE_ID,
    runtime_driver,
)
from tests.services.test_server_launch_service import (
    committed_launch_fixture as committed_launch_fixture,
)


async def fetch_operation(operation_id):
    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        return await db.get(ServerLaunchOperation, operation_id)


async def wait_for_operation(operation_id, predicate, *, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        row = await fetch_operation(operation_id)
        if row is not None and predicate(row):
            return row
        if time.monotonic() >= deadline:
            raise AssertionError("Launch operation heartbeat condition was not reached")
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("fails", [False, True])
@pytest.mark.asyncio
async def test_slow_spawn_heartbeats_and_stops_before_finalization(
    committed_launch_fixture, monkeypatch, fails
):
    fixture = committed_launch_fixture
    executor_id = uuid.uuid4()
    monkeypatch.setattr(
        heartbeat_module,
        "_api_worker_heartbeat",
        SimpleNamespace(executor_id=executor_id),
    )
    monkeypatch.setattr(heartbeat_module, "_celery_worker_heartbeat", None)
    monkeypatch.setattr(settings, "operation_heartbeat_interval_seconds", 0.05)

    entered = asyncio.Event()
    release = asyncio.Event()

    async with AsyncSession(test_engine, expire_on_commit=False) as db:
        service = ServerLaunchService(
            db,
            runtime_driver(),
            heartbeat_session_factory=async_sessionmaker(test_engine, expire_on_commit=False),
        )
        request = fixture.request()
        revision_id = await service.resolve_revision(fixture.owner_id, request)
        reservation = await service.reserve(fixture.owner_id, request, revision_id)
        assert isinstance(reservation, LaunchReservation)
        await db.commit()

        async def slow_spawn(**kwargs):
            entered.set()
            await release.wait()
            if fails:
                raise RuntimeError("late runtime outcome")
            return Server(
                id=reservation.server_id,
                container_id="slow-runtime",
                image=IMAGE_ID,
                external_url="https://slow.example.test",
                health_status="healthy",
            )

        service.spawner.spawn = AsyncMock(side_effect=slow_spawn)
        provision = asyncio.create_task(service.provision(reservation))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)

            operation_id = reservation.operation_id
            first = await wait_for_operation(operation_id, lambda row: row.heartbeat_at is not None)
            assert first.executor_id == executor_id
            await wait_for_operation(
                operation_id, lambda row: row.heartbeat_at > first.heartbeat_at
            )

            release.set()
            if fails:
                with pytest.raises(LaunchError, match="recovery_required"):
                    await asyncio.wait_for(provision, timeout=10)
                finished = await fetch_operation(operation_id)
                assert finished.state == "uncertain"
            else:
                server = await asyncio.wait_for(provision, timeout=10)
                assert server.status == "running"
                finished = await fetch_operation(operation_id)
                assert finished.state == "succeeded"
        finally:
            release.set()
            if not provision.done():
                provision.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await provision

        last_beat = finished.heartbeat_at
        assert last_beat is not None
        await asyncio.sleep(0.2)
        assert (await fetch_operation(operation_id)).heartbeat_at == last_beat
