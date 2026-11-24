# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Queue persistence and concurrent state transitions against PostgreSQL."""

import asyncio
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container.driver import ContainerDriverError
from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.models.user import User
from app.services.resource_pool_service import ResourcePoolService
from app.services.server_queue_dispatch_service import ServerQueueDispatchService
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


class QueueRuntime:
    """Read-only runtime double for orphan proof tests."""

    def __init__(self):
        self.containers = []
        self.named = {}
        self.inspect = {}
        self.fail = False

    async def list_containers(self, filters=None, *, all=False):
        if self.fail:
            raise ContainerDriverError("runtime unavailable", status=500)
        return self.containers

    async def get_container_info(self, container_id):
        if self.fail:
            raise ContainerDriverError("runtime unavailable", status=500)
        if container_id not in self.inspect:
            raise ContainerDriverError("not found", status=404)
        return self.inspect[container_id]

    async def get_container_by_name(self, name):
        if self.fail:
            raise ContainerDriverError("runtime unavailable", status=500)
        return self.named.get(name)


async def starting_request(
    db,
    rows,
    *,
    name=None,
    server_status="starting",
    operation_state=None,
    operation_reason=None,
    started_at=None,
):
    name = name or f"starting-{uuid.uuid4().hex[:8]}"
    entry = await enqueue(db, rows, name=name)
    entry.status = "starting"
    entry.claim_token = uuid.uuid4()
    entry.claimed_at = utc_now()
    entry.reason_code = None
    server = Server(
        name=name,
        user_id=entry.user_id,
        status=server_status,
        started_at=started_at,
    )
    db.add(server)
    await db.flush()
    entry.server_id = server.id
    operation = None
    if operation_state is not None:
        operation = ServerLaunchOperation(
            id=server.id,
            server_id=server.id,
            owner_id=entry.user_id,
            action="create",
            state=operation_state,
            fencing_token=uuid.uuid4(),
            revision_id=None,
            request_payload=None,
            mounts=[],
            gpu_devices=[],
            username=rows[0].username,
            resources={"cpu": 1, "memory": "1g", "disk": "2g", "gpu": 0},
            generation=1,
            reason_code=operation_reason,
        )
        db.add(operation)
    await db.flush()
    return entry, server, operation


@pytest.mark.asyncio
async def test_reconcile_starting_success_uses_server_start_time_once(db_session, queue_rows):
    started_at = utc_now() - timedelta(seconds=5)
    entry, server, _ = await starting_request(
        db_session,
        queue_rows,
        operation_state="succeeded",
        server_status="running",
        started_at=started_at,
    )
    queue_id, server_id = entry.id, server.id
    await db_session.commit()

    first = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert first.scanned == 1
    assert first.started == 1
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "started"
    assert stored.started_at == started_at
    assert stored.reason_code is None
    assert stored.server_id == server_id
    updated_at = stored.updated_at

    second = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert second.scanned == 0
    refreshed = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert refreshed.updated_at == updated_at


@pytest.mark.asyncio
async def test_reconcile_starting_failure_preserves_safe_operation_reason(db_session, queue_rows):
    entry, _, _ = await starting_request(
        db_session,
        queue_rows,
        operation_state="failed",
        operation_reason="runtime_absent",
        server_status="error",
    )
    await db_session.commit()

    result = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert result.failed == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "failed"
    assert stored.reason_code == "runtime_absent"
    assert stored.failed_at is not None
    assert stored.started_at is None


@pytest.mark.asyncio
async def test_reconcile_starting_failure_never_exposes_unbounded_reason(db_session, queue_rows):
    entry, _, _ = await starting_request(
        db_session,
        queue_rows,
        operation_state="failed",
        operation_reason="raw /private/path: password=secret",
        server_status="error",
    )
    await db_session.commit()

    await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "failed"
    assert stored.reason_code == "configuration_changed"
    assert "secret" not in stored.reason_code


@pytest.mark.asyncio
async def test_reconcile_starting_uncertain_stays_operator_visible(db_session, queue_rows):
    entry, server, _ = await starting_request(
        db_session,
        queue_rows,
        operation_state="uncertain",
        operation_reason="recovery_required",
    )
    queue_id, server_id = entry.id, server.id
    await db_session.commit()

    first = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert first.recovery_required == 1
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"
    assert stored.server_id == server_id
    updated_at = stored.updated_at

    second = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert second.recovery_required == 1
    refreshed = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert refreshed.status == "starting"
    assert refreshed.reason_code == "recovery_required"
    assert refreshed.updated_at == updated_at


@pytest.mark.asyncio
async def test_reconcile_starting_active_operation_is_never_requeued(db_session, queue_rows):
    entry, _, _ = await starting_request(db_session, queue_rows, operation_state="executing")
    await db_session.commit()

    result = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert result.deferred == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code is None


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_cancels_only_after_runtime_absence(db_session, queue_rows):
    entry, _, _ = await starting_request(db_session, queue_rows, server_status="starting")
    await db_session.commit()

    result = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert result.cancelled == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "cancelled"
    assert stored.reason_code == "configuration_changed"

    second = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert second.scanned == 0


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_with_runtime_stays_recovery_required(
    db_session, queue_rows
):
    entry, server, _ = await starting_request(db_session, queue_rows, server_status="starting")
    await db_session.commit()
    runtime = QueueRuntime()
    runtime.containers = [
        {
            "Id": "orphan-container",
            "Config": {"Labels": {"nukelab.server.id": str(server.id)}},
            "State": {"Running": True},
        }
    ]

    result = await ServerQueueService(db_session).reconcile_starting(runtime)
    assert result.recovery_required == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_with_unknown_runtime_stays_recovery_required(
    db_session, queue_rows
):
    entry, _, _ = await starting_request(db_session, queue_rows, server_status="starting")
    await db_session.commit()
    runtime = QueueRuntime()
    runtime.fail = True

    result = await ServerQueueService(db_session).reconcile_starting(runtime)
    assert result.recovery_required == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_with_recorded_container_requires_recovery(
    db_session, queue_rows
):
    entry, server, _ = await starting_request(db_session, queue_rows, server_status="starting")
    server.container_id = "recorded-container"
    queue_id = entry.id
    await db_session.commit()
    runtime = QueueRuntime()
    runtime.inspect["recorded-container"] = {"Id": "recorded-container"}

    result = await ServerQueueService(db_session).reconcile_starting(runtime)
    assert result.recovery_required == 1
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_with_launch_name_requires_recovery(db_session, queue_rows):
    entry, server, _ = await starting_request(db_session, queue_rows, server_status="starting")
    queue_id = entry.id
    await db_session.commit()
    runtime = QueueRuntime()
    runtime.named[f"nukelab-launch-{server.id}"] = "named-container"

    result = await ServerQueueService(db_session).reconcile_starting(runtime)
    assert result.recovery_required == 1
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"


@pytest.mark.asyncio
async def test_reconcile_starting_orphan_without_server_identity_is_not_cancelled(
    db_session, queue_rows
):
    entry = await enqueue(db_session, queue_rows, name="no-identity")
    entry.status = "starting"
    entry.claim_token = uuid.uuid4()
    await db_session.commit()

    result = await ServerQueueService(db_session).reconcile_starting(QueueRuntime())
    assert result.recovery_required == 1
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code == "recovery_required"


@pytest.mark.asyncio
async def test_owner_cancel_never_touches_starting_request(db_session, queue_rows):
    entry, _, _ = await starting_request(db_session, queue_rows, operation_state="executing")
    await db_session.commit()

    with pytest.raises(QueueError) as error:
        await ServerQueueService(db_session).cancel(entry.id, entry.user_id)
    assert error.value.code == "launch_in_progress"
    assert error.value.status_code == 409
    stored = await db_session.get(ServerQueue, entry.id, populate_existing=True)
    assert stored.status == "starting"


@pytest.mark.asyncio
async def test_claim_refuses_queue_that_already_owns_a_launch_operation(db_session, queue_rows):
    entry = await enqueue(db_session, queue_rows, name="already-linked")
    server = Server(name="already-linked", user_id=entry.user_id, status="starting")
    db_session.add(server)
    await db_session.flush()
    entry.server_id = server.id
    operation = ServerLaunchOperation(
        id=server.id,
        server_id=server.id,
        owner_id=entry.user_id,
        action="create",
        state="succeeded",
        fencing_token=uuid.uuid4(),
        revision_id=None,
        request_payload=None,
        mounts=[],
        gpu_devices=[],
        username=queue_rows[0].username,
        resources={"cpu": 1, "memory": "1g", "disk": "2g", "gpu": 0},
        generation=1,
    )
    db_session.add(operation)
    queue_id = entry.id
    await db_session.commit()

    with pytest.raises(QueueError) as error:
        async with db_session.begin():
            await ServerQueueService(db_session).claim(
                queue_id, server_id=uuid.uuid4(), claim_token=uuid.uuid4()
            )
    assert error.value.code == "launch_in_progress"
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "pending"
    assert stored.claim_token is None


@pytest.mark.asyncio
async def test_dispatch_never_redispatches_a_claimed_request(db_session, queue_rows):
    entry, _, _ = await starting_request(db_session, queue_rows, operation_state="executing")
    queue_id = entry.id
    await db_session.commit()
    dispatcher = ServerQueueDispatchService(db_session, QueueRuntime())
    dispatcher.launch.reserve = AsyncMock()
    dispatcher.launch.provision = AsyncMock()

    result = await dispatcher.dispatch()

    assert result.reconciled == 1
    assert result.started == 0
    dispatcher.launch.reserve.assert_not_awaited()
    dispatcher.launch.provision.assert_not_awaited()
    stored = await db_session.get(ServerQueue, queue_id, populate_existing=True)
    assert stored.status == "starting"
    assert stored.reason_code is None


@pytest.mark.asyncio
async def test_concurrent_queue_reconciliation_produces_one_start_transition():
    marker = uuid.uuid4().hex
    async with AsyncSession(test_engine, expire_on_commit=False) as seed:
        async with seed.begin():
            owner = User(username=f"recover-{marker}", email=f"{marker}@example.test")
            plan = ServerPlan(name=f"recover-{marker}", slug=f"recover-{marker}")
            environment = EnvironmentTemplate(
                name=f"recover-{marker}", slug=f"recover-{marker}", image="img"
            )
            seed.add_all([owner, plan, environment])
            await seed.flush()
            server = Server(
                name=f"recover-{marker}",
                user_id=owner.id,
                status="running",
                started_at=utc_now(),
            )
            seed.add(server)
            await seed.flush()
            queue = ServerQueue(
                user_id=owner.id,
                plan_id=plan.id,
                environment_id=environment.id,
                status="starting",
                server_name=server.name,
                server_id=server.id,
                claim_token=uuid.uuid4(),
                requested_at=utc_now(),
            )
            seed.add(queue)
            seed.add(
                ServerLaunchOperation(
                    id=server.id,
                    server_id=server.id,
                    owner_id=owner.id,
                    action="create",
                    state="succeeded",
                    fencing_token=uuid.uuid4(),
                    revision_id=None,
                    request_payload=None,
                    mounts=[],
                    gpu_devices=[],
                    username=owner.username,
                    resources={"cpu": 1, "memory": "1g", "disk": "2g", "gpu": 0},
                    generation=1,
                )
            )
            await seed.flush()
            queue_id, server_id = queue.id, server.id
            owner_id, plan_id, environment_id = owner.id, plan.id, environment.id
    gate = asyncio.Event()

    async def reconcile():
        async with AsyncSession(test_engine) as db:
            await gate.wait()
            return await ServerQueueService(db).reconcile_starting(QueueRuntime())

    try:
        left_task = asyncio.create_task(reconcile())
        right_task = asyncio.create_task(reconcile())
        gate.set()
        left, right = await asyncio.wait_for(asyncio.gather(left_task, right_task), timeout=10)
        assert left.started + right.started == 1
        async with AsyncSession(test_engine) as verify:
            stored = await verify.get(ServerQueue, queue_id, populate_existing=True)
            assert stored.status == "started"
            assert stored.started_at is not None
    finally:
        async with AsyncSession(test_engine) as cleanup, cleanup.begin():
            await cleanup.execute(
                delete(ServerLaunchOperation).where(ServerLaunchOperation.server_id == server_id)
            )
            await cleanup.execute(delete(ServerQueue).where(ServerQueue.id == queue_id))
            await cleanup.execute(delete(Server).where(Server.id == server_id))
            await cleanup.execute(
                delete(EnvironmentTemplate).where(EnvironmentTemplate.id == environment_id)
            )
            await cleanup.execute(delete(ServerPlan).where(ServerPlan.id == plan_id))
            await cleanup.execute(delete(User).where(User.id == owner_id))


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
