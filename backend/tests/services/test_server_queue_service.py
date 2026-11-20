# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Queue persistence and concurrent state transitions against PostgreSQL."""

import asyncio
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.user import User
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_queue_service import QueueError, ServerQueueService
from tests.conftest import test_engine


@pytest_asyncio.fixture
async def queue_rows(db_session, test_user):
    plan = ServerPlan(name="Queue plan", slug="queue-plan", cpu_limit=2)
    environment = EnvironmentTemplate(name="Queue env", slug="queue-env", image="approved")
    db_session.add_all([plan, environment])
    await db_session.flush()
    return test_user, plan, environment


async def enqueue(db, rows, name="waiting", **kwargs):
    owner, plan, environment = rows
    return await ServerQueueService(db).enqueue(
        owner_id=owner.id,
        name=name,
        plan_id=plan.id,
        environment_id=environment.id,
        request_payload={
            "name": name,
            "volume_mounts": [
                {
                    "volume_id": "",
                    "mount_path": "/home/user/data",
                    "mode": "rw",
                    "max_size_bytes": 1024,
                },
            ],
        },
        plan_snapshot={"cpu": 2, "memory": "4g", "disk": "20g", "gpu_count": 1, "cost_per_hour": 2},
        revision_id=uuid.uuid4(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_enqueue_preserves_complete_intent_without_committing(db_session, queue_rows):
    entry = await enqueue(db_session, queue_rows)
    assert entry.request_payload["volume_mounts"][0]["volume_id"] == ""
    assert entry.request_payload["volume_mounts"][0]["max_size_bytes"] == 1024
    assert entry.request_version == 1
    assert entry.plan_snapshot["cost_per_hour"] == 2
    assert entry.requested_gpu == 1
    assert db_session.in_transaction()
    dto = await ServerQueueService(db_session).describe(entry)
    assert dto.position == 1
    assert dto.request.resources.memory_mib == 4096
    assert dto.can_cancel
    assert "volume_mounts" not in dto.model_dump_json()


@pytest.mark.asyncio
async def test_enqueue_duplicate_and_bounds(db_session, queue_rows):
    entry = await enqueue(db_session, queue_rows)
    with pytest.raises(QueueError) as duplicate:
        await enqueue(db_session, queue_rows)
    assert duplicate.value.queue_id == entry.id
    assert duplicate.value.status_code == 409
    with pytest.raises(QueueError) as full:
        await enqueue(db_session, queue_rows, name="second", max_per_owner=1)
    assert full.value.status_code == 429


@pytest.mark.asyncio
async def test_cancel_idempotent_and_foreign_hidden(db_session, queue_rows):
    entry = await enqueue(db_session, queue_rows)
    service = ServerQueueService(db_session)
    with pytest.raises(QueueError) as foreign:
        await service.cancel(entry.id, uuid.uuid4())
    assert foreign.value.status_code == 404
    await service.cancel(entry.id, entry.user_id)
    again = await service.cancel(entry.id, entry.user_id)
    assert again.status == "cancelled"
    assert again.reason_code == "request_cancelled"
    assert (await service.describe(again)).position is None
    entry.status = "started"
    await db_session.flush()
    with pytest.raises(QueueError) as started:
        await service.cancel(entry.id, entry.user_id)
    assert started.value.status_code == 409


@pytest.mark.asyncio
async def test_positions_priority_timestamp_uuid_and_terminal(db_session, queue_rows):
    entries = [await enqueue(db_session, queue_rows, name=f"request-{i}") for i in range(3)]
    now = utc_now()
    for entry in entries:
        entry.requested_at = now
    entries[2].priority = 5
    await db_session.flush()
    pool = ResourcePoolService(db_session)
    expected = [entries[2], *sorted(entries[:2], key=lambda entry: entry.id)]
    assert [await pool.get_queue_position(str(entry.id)) for entry in expected] == [1, 2, 3]
    expected[0].status = "starting"
    await db_session.flush()
    assert await pool.get_queue_position(str(expected[0].id)) is None
    assert await pool.get_queue_position(str(uuid.uuid4())) is None


@pytest.mark.asyncio
async def test_expiry_never_cancels_starting(db_session, queue_rows):
    pending = await enqueue(db_session, queue_rows)
    starting = await enqueue(db_session, queue_rows, name="starting")
    pending.expires_at = starting.expires_at = utc_now() - timedelta(seconds=1)
    starting.status = "starting"
    await db_session.flush()
    assert await ServerQueueService(db_session).expire_pending() == 1
    await db_session.refresh(pending)
    await db_session.refresh(starting)
    assert pending.reason_code == "queue_expired"
    assert starting.status == "starting"


@pytest.mark.asyncio
async def test_owner_pagination_and_sanitized_failure(db_session, queue_rows):
    entry = await enqueue(db_session, queue_rows)
    entry.error_message = "/private/host/path: password=secret"
    entry.status = "failed"
    await db_session.flush()
    service = ServerQueueService(db_session)
    result = await service.list_owned(entry.user_id, statuses=["failed"])
    assert result.total == 1
    assert result.items[0].position is None
    assert "secret" not in result.model_dump_json()
    assert (await service.list_owned(uuid.uuid4())).total == 0


@pytest.mark.asyncio
async def test_two_postgres_sessions_cancel_or_claim_has_one_winner():
    """Independent committed transactions expose actual lock/state races."""
    marker = uuid.uuid4().hex
    async with AsyncSession(test_engine, expire_on_commit=False) as seed:
        async with seed.begin():
            owner = User(username=f"queue-{marker}", email=f"{marker}@example.test")
            plan = ServerPlan(name=f"queue-{marker}", slug=f"queue-{marker}")
            env = EnvironmentTemplate(name=f"queue-{marker}", slug=f"queue-{marker}", image="img")
            seed.add_all([owner, plan, env])
            await seed.flush()
            server = Server(name=f"queue-{marker}", user_id=owner.id, status="starting")
            seed.add(server)
            await seed.flush()
            entry = await enqueue(seed, (owner, plan, env))
            entry_id, owner_id, server_id = entry.id, owner.id, server.id
    gate = asyncio.Event()

    async def claim():
        async with AsyncSession(test_engine) as db, db.begin():
            await gate.wait()
            return (
                await ServerQueueService(db).claim(
                    entry_id,
                    server_id=server_id,
                    claim_token=uuid.uuid4(),
                )
                is not None
            )

    async def cancel():
        async with AsyncSession(test_engine) as db, db.begin():
            await gate.wait()
            try:
                await ServerQueueService(db).cancel(entry_id, owner_id)
                return True
            except QueueError as exc:
                assert exc.status_code == 409
                return False

    try:
        claim_task, cancel_task = asyncio.create_task(claim()), asyncio.create_task(cancel())
        gate.set()
        outcomes = await asyncio.wait_for(asyncio.gather(claim_task, cancel_task), timeout=10)
        assert sum(outcomes) == 1
        async with AsyncSession(test_engine) as verify:
            stored = await verify.scalar(select(ServerQueue).where(ServerQueue.id == entry_id))
            assert stored.status in {"starting", "cancelled"}
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(delete(ServerQueue).where(ServerQueue.id == entry_id))
            await cleanup.execute(delete(Server).where(Server.id == server_id))
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == env.id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == plan.id))
            await cleanup.execute(delete(User).where(User.id == owner_id))
