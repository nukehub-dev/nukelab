# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""PostgreSQL rotating scan fairness and independent scanner cursor visibility."""

import asyncio
import json
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.time_utils import utc_now
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.system_setting import SystemSetting
from app.schemas.server_queue import QueuedServerResponse
from app.services.server_launch_service import ServerLaunchService
from app.services.server_queue_dispatch_service import ServerQueueDispatchService, _decode_cursor
from tests.services.test_server_launch_service import IMAGE_ID, runtime_driver
from tests.services.test_server_launch_service import (
    committed_launch_fixture as committed_launch_fixture,
)
from tests.services.test_server_launch_service import launch_fixture as launch_fixture

CURSOR_KEY = "server_queue_dispatch_cursor"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "{",
        "null",
        "[]",
        "{}",
        "x" * 2049,
        json.dumps(
            {"version": 1, "priority": 2**63, "requested_at": None, "id": str(uuid.uuid4())}
        ),
        json.dumps({"version": True, "priority": 1, "requested_at": None, "id": str(uuid.uuid4())}),
        json.dumps(
            {
                "version": 1,
                "priority": 1,
                "requested_at": "2026-01-01T00:00:00+00:00",
                "id": str(uuid.uuid4()),
            }
        ),
        json.dumps({"version": 1, "priority": 1, "requested_at": None, "id": "invalid"}),
    ],
)
def test_corrupt_cursor_cannot_break_or_authorize_scan(raw):
    assert _decode_cursor(raw) is None


@pytest.mark.asyncio
async def test_bounded_rotation_reaches_later_fitting_request(
    db_session, launch_fixture, monkeypatch
):
    monkeypatch.setattr(settings, "resource_pool_cpu", 0.5)
    monkeypatch.setattr(settings, "queue_max_pending_per_owner", 10)
    large_plan = await db_session.get(ServerPlan, launch_fixture.plan_id)
    large_plan.cpu_limit = 2.0
    large_plan.priority = 10
    small_plan = ServerPlan(
        id=uuid.uuid4(),
        name="Small fitting",
        slug="small-fitting",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="2g",
        gpu_limit=0,
        cost_per_hour=1,
        is_active=True,
        is_public=True,
        priority=0,
    )
    db_session.add(small_plan)
    await db_session.commit()
    driver = runtime_driver()
    service = ServerLaunchService(db_session, driver)
    queued = []
    for index in range(5):
        request = launch_fixture.request("large-" + str(index) if index < 4 else "fits-later")
        if index == 4:
            request = request.model_copy(update={"plan_id": small_plan.id})
        revision_id = await service.resolve_revision(launch_fixture.owner_id, request)
        response = await service.reserve(launch_fixture.owner_id, request, revision_id)
        assert isinstance(response, QueuedServerResponse)
        queued.append(response.queue_id)
    monkeypatch.setattr(settings, "resource_pool_cpu", 1.0)
    dispatcher = ServerQueueDispatchService(db_session, driver)

    async def spawn(**kwargs):
        return Server(
            id=uuid.UUID(kwargs["server_id"]),
            container_id="cursor-runtime",
            image=IMAGE_ID,
            health_status="healthy",
            external_url="https://runtime.example.test",
        )

    dispatcher.launch.spawner.spawn = AsyncMock(side_effect=spawn)
    first = await dispatcher.dispatch(batch_size=2)
    second = await dispatcher.dispatch(batch_size=2)
    third = await dispatcher.dispatch(batch_size=2)
    assert first.waiting == second.waiting == 2
    assert first.started == second.started == 0
    assert third.started == 1 and third.scanned == 1
    assert (await db_session.get(ServerQueue, queued[-1])).status == "started"
    for queue_id in queued[:-1]:
        assert (await db_session.get(ServerQueue, queue_id)).status == "pending"
    await db_session.commit()
    wrapped = await dispatcher.dispatch(batch_size=2)
    assert wrapped.scanned == 2 and wrapped.waiting == 2


@pytest.mark.asyncio
async def test_null_timestamp_legacy_request_is_cancelled_without_dispatch(
    db_session, launch_fixture
):
    queue = ServerQueue(
        user_id=launch_fixture.owner_id,
        plan_id=launch_fixture.plan_id,
        environment_id=launch_fixture.environment_id,
        server_name="legacy-null-time",
        request_payload=launch_fixture.request().model_dump(mode="json"),
        request_version=1,
        revision_id=uuid.uuid4(),
        priority=0,
        status="pending",
    )
    db_session.add(queue)
    await db_session.flush()
    await db_session.execute(
        update(ServerQueue).where(ServerQueue.id == queue.id).values(requested_at=None)
    )
    await db_session.commit()
    service = ServerQueueDispatchService(db_session, runtime_driver())
    service.launch.reserve = AsyncMock()
    result = await service.dispatch(batch_size=1)
    assert result.cancelled == 1
    assert (await db_session.get(ServerQueue, queue.id)).reason_code == "configuration_changed"
    service.launch.reserve.assert_not_awaited()
    value = (await db_session.get(SystemSetting, CURSOR_KEY)).value
    assert json.loads(value)["requested_at"] is None


@pytest.mark.asyncio
async def test_equal_priority_time_uses_uuid_and_wraps_even_after_cursor_row_deleted(
    db_session, launch_fixture
):
    timestamp = utc_now() - timedelta(minutes=1)
    ids = sorted(uuid.uuid4() for _ in range(3))
    for index, queue_id in enumerate(ids):
        db_session.add(
            ServerQueue(
                id=queue_id,
                user_id=launch_fixture.owner_id,
                plan_id=launch_fixture.plan_id,
                environment_id=launch_fixture.environment_id,
                server_name="cursor-tie-" + str(index),
                requested_at=timestamp,
                priority=0,
                status="pending",
            )
        )
    db_session.add(SystemSetting(key=CURSOR_KEY, value="broken cursor"))
    await db_session.commit()
    dispatcher = ServerQueueDispatchService(db_session, runtime_driver())
    async with db_session.begin():
        first = await dispatcher._scan_batch(1)
        first_id = first[0].id
    assert first_id == ids[0]
    async with db_session.begin():
        await db_session.execute(delete(ServerQueue).where(ServerQueue.id == first_id))
        next_rows = await dispatcher._scan_batch(2)
        next_ids = [row.id for row in next_rows]
    assert next_ids == ids[1:]
    async with db_session.begin():
        assert [row.id for row in await dispatcher._scan_batch(2)] == ids[1:]


@pytest.mark.asyncio
async def test_independent_scanners_commit_distinct_rotating_snapshots(committed_launch_fixture):
    from tests.conftest import test_engine

    fixture = committed_launch_fixture
    ids = sorted(uuid.uuid4() for _ in range(4))
    old_cursor = None
    try:
        async with AsyncSession(test_engine) as db, db.begin():
            old_cursor = await db.scalar(
                select(SystemSetting.value).where(SystemSetting.key == CURSOR_KEY)
            )
            await db.execute(delete(SystemSetting).where(SystemSetting.key == CURSOR_KEY))
            for index, queue_id in enumerate(ids):
                db.add(
                    ServerQueue(
                        id=queue_id,
                        user_id=fixture.owner_id,
                        plan_id=fixture.plan_id,
                        environment_id=fixture.environment_id,
                        server_name="parallel-cursor-" + str(index),
                        requested_at=utc_now(),
                        priority=0,
                        status="pending",
                    )
                )
        barrier = asyncio.Barrier(2)

        async def scan():
            async with AsyncSession(test_engine) as db:
                service = ServerQueueDispatchService(db, runtime_driver())
                await barrier.wait()
                async with db.begin():
                    return [row.id for row in await service._scan_batch(2)]

        left, right = await asyncio.wait_for(asyncio.gather(scan(), scan()), timeout=10)
        assert len(left) == len(right) == 2
        assert not set(left) & set(right)
        assert set(left + right) == set(ids)
    finally:
        async with AsyncSession(test_engine) as db, db.begin():
            await db.execute(delete(ServerQueue).where(ServerQueue.id.in_(ids)))
            await db.execute(delete(SystemSetting).where(SystemSetting.key == CURSOR_KEY))
            if old_cursor is not None:
                db.add(SystemSetting(key=CURSOR_KEY, value=old_cursor))
