# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Admission helpers retain caller transactions and count durable reservations once."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, update

from app.config import settings
from app.core.time_utils import utc_now
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.volume import Volume
from app.services.gpu_allocator import GpuAllocatorService
from app.services.quota_service import QuotaService


def forbid_boundary(db):
    """An accidental helper commit/rollback would release admission serialization."""
    return (
        patch.object(db, "commit", AsyncMock(side_effect=AssertionError("caller owns commit"))),
        patch.object(db, "rollback", AsyncMock(side_effect=AssertionError("caller owns rollback"))),
    )


@pytest.mark.asyncio
async def test_quota_creation_and_volume_check_do_not_commit(db_session, test_user):
    service = QuotaService(db_session)
    commit_patch, rollback_patch = forbid_boundary(db_session)
    with commit_patch, rollback_patch:
        quota = await service.get_or_create_user_quota(str(test_user.id), commit=False)
        assert quota.id is not None
        result = await service.check_volume_creation_allowed(
            str(test_user.id),
            requested_size_bytes=1024**3,
            commit=False,
        )
        assert result["allowed"]
        assert db_session.in_transaction()
        assert (
            await db_session.scalar(
                select(ResourceQuota.id).where(
                    ResourceQuota.user_id == test_user.id,
                )
            )
            == quota.id
        )


@pytest.mark.asyncio
async def test_spawn_check_and_increment_recount_reservations_once(
    db_session, test_user, monkeypatch
):
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    plan = ServerPlan(
        name="admission-plan",
        slug="admission-plan",
        cpu_limit=2,
        memory_limit="4g",
        disk_limit="20g",
        gpu_limit=0,
        max_servers_per_user=1,
    )
    quota = ResourceQuota(
        user_id=test_user.id,
        max_cpu_total=2,
        max_memory_total="4g",
        max_servers_total=1,
        max_gpu_total=0,
        max_disk_total="10g",
    )
    db_session.add_all([plan, quota])
    await db_session.flush()
    server = Server(
        name="reserved",
        user_id=test_user.id,
        plan_id=plan.id,
        status="starting",
        allocated_cpu=2,
        allocated_memory="4g",
        allocated_gpu=0,
    )
    volume = Volume(
        name="admission-volume", display_name="Data", owner_id=test_user.id, max_size_bytes=1024**3
    )
    db_session.add_all([server, volume])
    await db_session.flush()
    service = QuotaService(db_session)
    commit_patch, rollback_patch = forbid_boundary(db_session)
    with (
        commit_patch,
        rollback_patch,
        patch.object(GpuAllocatorService, "reconcile", AsyncMock()) as reconcile,
    ):
        # Rechecking this same reservation must exclude it from both total and per-plan counts.
        result = await service.check_spawn_allowed(
            str(test_user.id),
            str(plan.id),
            exclude_server_id=str(server.id),
            commit=False,
        )
        assert result["allowed"]
        for _ in range(2):
            observed = await service.increment_usage(str(test_user.id), str(plan.id), commit=False)
            assert observed.usage_cpu == 2
            assert observed.usage_memory_mb == 4096
            assert observed.usage_servers == 1
            assert observed.usage_disk_mb == 1024
        denied = await service.check_spawn_allowed(str(test_user.id), str(plan.id), commit=False)
        assert not denied["allowed"]
        reconcile.assert_not_awaited()
        assert db_session.in_transaction()


@pytest.mark.asyncio
async def test_accounting_refreshes_cached_limits_servers_and_volumes(db_session, test_user):
    quota = ResourceQuota(user_id=test_user.id, max_cpu_total=100)
    server = Server(
        name="stale-server",
        user_id=test_user.id,
        status="stopped",
        allocated_cpu=1,
        allocated_memory="1g",
        allocated_gpu=0,
    )
    volume = Volume(
        name="stale-volume", display_name="Data", owner_id=test_user.id, max_size_bytes=1024**3
    )
    db_session.add_all([quota, server, volume])
    await db_session.flush()
    # Simulate committed changes visible after admission waits, keeping stale ORM instances.
    for statement in (
        update(ResourceQuota).where(ResourceQuota.id == quota.id).values(max_cpu_total=3),
        update(Server).where(Server.id == server.id).values(status="starting", allocated_cpu=3),
        update(Volume).where(Volume.id == volume.id).values(max_size_bytes=2 * 1024**3),
    ):
        await db_session.execute(statement.execution_options(synchronize_session=False))
    assert quota.max_cpu_total == 100
    assert server.status == "stopped"
    assert volume.max_size_bytes == 1024**3
    commit_patch, rollback_patch = forbid_boundary(db_session)
    with commit_patch, rollback_patch:
        actual = await QuotaService(db_session).recalculate_usage(str(test_user.id), commit=False)
        assert actual.max_cpu_total == 3
        assert actual.usage_cpu == 3
        assert actual.usage_servers == 1
        assert actual.usage_disk_mb == 2048


@pytest.mark.asyncio
async def test_gpu_reserve_release_and_reconcile_leave_transaction_owned(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0,nvidia.com/gpu=1")
    allocator = GpuAllocatorService(db_session)
    server_id = str(uuid.uuid4())
    commit_patch, rollback_patch = forbid_boundary(db_session)
    with commit_patch, rollback_patch:
        assert await allocator.allocate(server_id, 1, commit=False) == ["nvidia.com/gpu=0"]
        await allocator.release(server_id, commit=False)
        assert await allocator.devices_for(server_id) == []
        db_session.add(
            GpuAllocation(
                server_id=uuid.uuid4(),
                device="nvidia.com/gpu=1",
                created_at=utc_now() - timedelta(minutes=30),
            )
        )
        await db_session.flush()
        await allocator.reconcile(commit=False)
        assert await allocator.allocated_devices() == set()
        assert db_session.in_transaction()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit", [False, True])
async def test_gpu_unique_race_rolls_back_only_savepoint(
    db_session, test_user, monkeypatch, commit
):
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    holder = uuid.uuid4()
    reservation = Server(name="caller-reservation", user_id=test_user.id, status="starting")
    db_session.add_all([reservation, GpuAllocation(server_id=holder, device="nvidia.com/gpu=0")])
    await db_session.flush()
    reservation_id = reservation.id
    allocator = GpuAllocatorService(db_session)
    commit_patch, rollback_patch = forbid_boundary(db_session)
    with (
        commit_patch,
        rollback_patch,
        patch.object(allocator, "available", AsyncMock(return_value=["nvidia.com/gpu=0"])),
    ):
        # Force the stale available-device result seen when another allocator wins.
        assert await allocator.allocate(str(uuid.uuid4()), 1, commit=commit) is None
        assert await allocator.devices_for(str(holder)) == ["nvidia.com/gpu=0"]
        assert (
            await db_session.scalar(select(Server.id).where(Server.id == reservation_id))
            == reservation_id
        )
        assert db_session.in_transaction()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_gpu_quota,expected", [(0, False), (4, True)])
async def test_launch_can_defer_physical_gpu_capacity_but_not_owner_quota(
    db_session, test_user, monkeypatch, user_gpu_quota, expected
):
    monkeypatch.setattr(settings, "gpu_devices", "nvidia.com/gpu=0")
    plan = ServerPlan(
        name="gpu-capacity-plan",
        slug="gpu-capacity-plan",
        cpu_limit=1,
        memory_limit="1g",
        gpu_limit=1,
        is_public=True,
    )
    quota = ResourceQuota(user_id=test_user.id, max_gpu_total=user_gpu_quota)
    db_session.add_all(
        [plan, quota, GpuAllocation(server_id=uuid.uuid4(), device="nvidia.com/gpu=0")]
    )
    await db_session.flush()
    service = QuotaService(db_session)
    deferred = await service.check_spawn_allowed(
        str(test_user.id),
        str(plan.id),
        commit=False,
        include_gpu_pool=False,
    )
    assert deferred["allowed"] is expected
    default = await service.check_spawn_allowed(str(test_user.id), str(plan.id), commit=False)
    assert not default["allowed"]
    if user_gpu_quota == 0:
        assert "GPU limit exceeded" in deferred["reason"]
    else:
        assert "No GPUs available" in default["reason"]
