# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the exclusive GPU device allocator.

Covers the gpu_devices config parsing, GpuAllocatorService pool bookkeeping
(allocate / release / available / reconcile), the quota pool-exhaustion
check, and the create-server API preserving uncertain launch reservations.
"""

import uuid as uuid_mod
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_launch_operation import ServerLaunchOperation
from app.models.server_plan import ServerPlan
from app.models.server_queue import ServerQueue
from app.services.gpu_allocator import GpuAllocatorService
from app.services.quota_service import QuotaService
from tests.api.servers.conftest import server_api_runtime as server_api_runtime

POOL = "nvidia.com/gpu=0,nvidia.com/gpu=1"

# Older than GpuAllocatorService._RECONCILE_GRACE so reconcile() may reap them.
STALE_TS = utc_now() - timedelta(minutes=30)


@pytest.fixture
def gpu_pool(monkeypatch):
    """Configure a two-device exclusive pool for the duration of a test."""
    monkeypatch.setattr(settings, "gpu_devices", POOL)
    return settings


class TestGpuDevicesConfig:
    """gpu_devices parsing into gpu_device_list."""

    def test_empty_pool_is_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_devices", "")
        assert settings.gpu_device_list == []

    def test_parses_and_strips_entries(self, monkeypatch):
        monkeypatch.setattr(settings, "gpu_devices", " nvidia.com/gpu=0, ,nvidia.com/gpu=1 ,")
        assert settings.gpu_device_list == ["nvidia.com/gpu=0", "nvidia.com/gpu=1"]


class TestGpuAllocatorService:
    """Pool bookkeeping: allocate, available, devices_for, release."""

    @pytest.mark.asyncio
    async def test_disabled_when_pool_empty(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "gpu_devices", "")
        allocator = GpuAllocatorService(db_session)
        assert allocator.enabled() is False
        assert await allocator.allocate(str(uuid_mod.uuid4()), 1) == []

    @pytest.mark.asyncio
    async def test_allocate_reserves_devices(self, db_session, gpu_pool):
        allocator = GpuAllocatorService(db_session)
        server_id = str(uuid_mod.uuid4())

        devices = await allocator.allocate(server_id, 2)

        assert devices == ["nvidia.com/gpu=0", "nvidia.com/gpu=1"]
        assert await allocator.devices_for(server_id) == devices
        assert await allocator.available() == []

    @pytest.mark.asyncio
    async def test_allocate_returns_none_when_pool_exhausted(self, db_session, gpu_pool):
        allocator = GpuAllocatorService(db_session)
        assert await allocator.allocate(str(uuid_mod.uuid4()), 2) is not None

        # Both devices are reserved; a second server cannot get one.
        assert await allocator.allocate(str(uuid_mod.uuid4()), 1) is None

    @pytest.mark.asyncio
    async def test_allocate_count_zero_returns_empty(self, db_session, gpu_pool):
        allocator = GpuAllocatorService(db_session)
        assert await allocator.allocate(str(uuid_mod.uuid4()), 0) == []

    @pytest.mark.asyncio
    async def test_release_frees_devices(self, db_session, gpu_pool):
        allocator = GpuAllocatorService(db_session)
        server_id = str(uuid_mod.uuid4())
        await allocator.allocate(server_id, 1)
        assert await allocator.available() == ["nvidia.com/gpu=1"]

        await allocator.release(server_id)

        assert await allocator.available() == ["nvidia.com/gpu=0", "nvidia.com/gpu=1"]
        assert await allocator.devices_for(server_id) == []
        # Idempotent: releasing again is a no-op.
        await allocator.release(server_id)

    @pytest.mark.asyncio
    async def test_second_server_gets_next_available_device(self, db_session, gpu_pool):
        allocator = GpuAllocatorService(db_session)
        first = await allocator.allocate(str(uuid_mod.uuid4()), 1)
        second = await allocator.allocate(str(uuid_mod.uuid4()), 1)
        assert first == ["nvidia.com/gpu=0"]
        assert second == ["nvidia.com/gpu=1"]


class TestGpuAllocatorReconcile:
    """reconcile() drops rows for stopped, GPU-less, or deleted servers."""

    @pytest.mark.asyncio
    async def test_reconcile_drops_stale_rows(self, db_session, test_user, gpu_pool):
        running = Server(
            name="gpu-running", user_id=test_user.id, status="running", allocated_gpu=1
        )
        stopped = Server(
            name="gpu-stopped", user_id=test_user.id, status="stopped", allocated_gpu=1
        )
        no_gpu = Server(name="gpu-none", user_id=test_user.id, status="running", allocated_gpu=0)
        db_session.add_all([running, stopped, no_gpu])
        await db_session.commit()

        db_session.add_all(
            [
                GpuAllocation(server_id=running.id, device="nvidia.com/gpu=0", created_at=STALE_TS),
                GpuAllocation(server_id=stopped.id, device="nvidia.com/gpu=1", created_at=STALE_TS),
                GpuAllocation(server_id=no_gpu.id, device="nvidia.com/gpu=2", created_at=STALE_TS),
                GpuAllocation(
                    server_id=uuid_mod.uuid4(), device="nvidia.com/gpu=3", created_at=STALE_TS
                ),
            ]
        )
        await db_session.commit()

        allocator = GpuAllocatorService(db_session)
        await allocator.reconcile()

        result = await db_session.execute(select(GpuAllocation.device))
        assert result.scalars().all() == ["nvidia.com/gpu=0"]

    @pytest.mark.asyncio
    async def test_reconcile_keeps_fresh_rows_within_grace(self, db_session, gpu_pool):
        # Fresh rows referencing a not-yet-created server (in-flight spawn)
        # must survive reconcile so the device is not double-booked.
        db_session.add(GpuAllocation(server_id=uuid_mod.uuid4(), device="nvidia.com/gpu=0"))
        await db_session.commit()

        allocator = GpuAllocatorService(db_session)
        await allocator.reconcile()

        assert await allocator.allocated_devices() == {"nvidia.com/gpu=0"}

    @pytest.mark.asyncio
    async def test_reconcile_keeps_running_server_rows(self, db_session, test_user, gpu_pool):
        server = Server(name="gpu-live", user_id=test_user.id, status="starting", allocated_gpu=1)
        db_session.add(server)
        await db_session.commit()
        db_session.add(
            GpuAllocation(server_id=server.id, device="nvidia.com/gpu=0", created_at=STALE_TS)
        )
        await db_session.commit()

        allocator = GpuAllocatorService(db_session)
        await allocator.reconcile()

        assert await allocator.devices_for(str(server.id)) == ["nvidia.com/gpu=0"]


class TestQuotaGpuPoolCheck:
    """check_spawn_allowed fails when the exclusive pool is exhausted."""

    @pytest_asyncio.fixture
    async def gpu_plan(self, db_session):
        plan = ServerPlan(
            id=uuid_mod.uuid4(),
            name=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
            slug=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
            cpu_limit=1.0,
            memory_limit="1g",
            disk_limit="10g",
            gpu_limit=1,
            max_servers_per_user=5,
            cost_per_hour=0,
            is_active=True,
            is_public=True,
        )
        db_session.add(plan)
        await db_session.commit()
        return plan

    @pytest_asyncio.fixture
    async def generous_quota(self, db_session, test_user):
        quota = ResourceQuota(
            user_id=test_user.id,
            max_cpu_total=64,
            max_memory_total="64g",
            max_disk_total="500g",
            max_gpu_total=8,
            max_servers_total=20,
        )
        db_session.add(quota)
        await db_session.commit()
        return quota

    @pytest.mark.asyncio
    async def test_allowed_when_pool_has_free_devices(
        self, db_session, test_user, gpu_pool, gpu_plan, generous_quota
    ):
        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(gpu_plan.id))
        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_rejected_when_pool_exhausted(
        self, db_session, test_user, gpu_pool, gpu_plan, generous_quota
    ):
        # Occupy both pool devices with a real running server (orphan rows
        # would be reaped by the reconcile inside check_spawn_allowed).
        holder = Server(name="gpu-holder", user_id=test_user.id, status="running", allocated_gpu=2)
        db_session.add(holder)
        await db_session.commit()
        allocator = GpuAllocatorService(db_session)
        assert await allocator.allocate(str(holder.id), 2) is not None

        service = QuotaService(db_session)
        result = await service.check_spawn_allowed(str(test_user.id), str(gpu_plan.id))
        assert result["allowed"] is False
        assert "No GPUs available on the host" in result["reason"]


@pytest_asyncio.fixture
async def gpu_plan_env(db_session, test_user):
    """A GPU plan and environment for create-server API tests."""
    plan = ServerPlan(
        id=uuid_mod.uuid4(),
        name=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        cpu_limit=1.0,
        memory_limit="1g",
        disk_limit="10g",
        gpu_limit=1,
        cost_per_hour=0,
        is_active=True,
        is_public=True,
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(
        id=uuid_mod.uuid4(),
        name=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        image="test-image",
    )
    quota = ResourceQuota(user_id=test_user.id, max_gpu_total=2)
    db_session.add_all([plan, env, quota])
    await db_session.commit()
    return plan, env


class TestCreateServerGpuAllocation:
    """Exclusive pool admission through the real launch service and a fake driver."""

    @pytest.mark.asyncio
    async def test_create_reserves_and_forwards_gpu_devices(
        self,
        client,
        user_token,
        db_session,
        gpu_plan_env,
        gpu_pool,
        monkeypatch,
        server_api_runtime,
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env
        request = {"name": "gpu-server", "plan_id": str(plan.id), "environment_id": str(env.id)}
        response = await client.post(
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}, json=request
        )
        assert response.status_code == 200, response.text
        assert response.json()["allocated_gpu"] == 1
        config = server_api_runtime.create_container.call_args.kwargs
        assert config["gpu_limit"] == 1 and config["gpu_devices"] == ["nvidia.com/gpu=0"]
        allocation = await db_session.scalar(select(GpuAllocation))
        assert str(allocation.server_id) == response.json()["id"]
        assert allocation.device == "nvidia.com/gpu=0"

    @pytest.mark.asyncio
    async def test_uncertain_create_keeps_gpu_allocation_until_runtime_reconciled(
        self,
        client,
        user_token,
        db_session,
        gpu_plan_env,
        gpu_pool,
        monkeypatch,
        server_api_runtime,
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env
        request = {"name": "gpu-server", "plan_id": str(plan.id), "environment_id": str(env.id)}
        server_api_runtime.create_container.side_effect = RuntimeError("unknown create outcome")
        response = await client.post(
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}, json=request
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "recovery_required"
        allocation = await db_session.scalar(select(GpuAllocation))
        assert allocation is not None and allocation.device == "nvidia.com/gpu=0"
        reserved = await db_session.get(Server, allocation.server_id)
        assert reserved.status == "starting" and reserved.status_reason == "recovery_required"
        operation = await db_session.get(ServerLaunchOperation, reserved.id)
        assert operation.state == "uncertain"
        server_api_runtime.delete_container.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exhausted_pool_queues_request_without_allocating_devices(
        self,
        client,
        user_token,
        admin_user,
        db_session,
        gpu_plan_env,
        gpu_pool,
        monkeypatch,
        server_api_runtime,
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env
        request = {"name": "gpu-server", "plan_id": str(plan.id), "environment_id": str(env.id)}
        holder = Server(
            id=uuid_mod.uuid4(),
            name="other-owner-gpu-holder",
            user_id=admin_user.id,
            status="running",
            allocated_gpu=2,
        )
        db_session.add(holder)
        await db_session.commit()
        holder_id = holder.id
        allocator = GpuAllocatorService(db_session)
        assert await allocator.allocate(str(holder_id), 2) == [
            "nvidia.com/gpu=0",
            "nvidia.com/gpu=1",
        ]
        response = await client.post(
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}, json=request
        )
        assert response.status_code == 202, response.text
        assert response.json()["queued"] is True
        queued = await db_session.get(ServerQueue, uuid_mod.UUID(response.json()["queue_id"]))
        assert queued.reason_code == "gpu_wait" and queued.requested_gpu == 1
        assert queued.request_payload["volume_mounts"][0]["volume_id"] == ""
        allocations = list(await db_session.scalars(select(GpuAllocation)))
        assert len(allocations) == 2 and {row.server_id for row in allocations} == {holder_id}
        assert await db_session.scalar(select(func.count()).select_from(Server)) == 1
        server_api_runtime.create_container.assert_not_awaited()
