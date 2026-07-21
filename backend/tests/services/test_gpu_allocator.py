# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the exclusive GPU device allocator.

Covers the gpu_devices config parsing, GpuAllocatorService pool bookkeeping
(allocate / release / available / reconcile), the quota pool-exhaustion
check, and the create-server API failure path releasing its reservation.
"""

import contextlib
import uuid as uuid_mod
from datetime import timedelta
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.config import settings
from app.core.time_utils import utc_now
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.resource_quota import ResourceQuota
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.volume import Volume
from app.services.gpu_allocator import GpuAllocatorService
from app.services.quota_service import QuotaService

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
async def gpu_plan_env(db_session):
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
    db_session.add_all([plan, env])
    await db_session.commit()
    return plan, env


def _create_server_mocks(db_session, spawn_side_effect):
    """Context manager mocking every service create_server touches."""

    @contextlib.contextmanager
    def _stack():
        with (
            mock.patch("app.api.servers.spawner.spawn", side_effect=spawn_side_effect),
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
            mock.patch("app.services.resource_pool_service.ResourcePoolService") as mock_pool_cls,
            mock.patch("app.services.credit_service.CreditService") as mock_credit_cls,
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
            mock.patch("app.services.volume_access_service.VolumeAccessService") as mock_access_cls,
        ):
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            mock_quota.increment_usage = mock.AsyncMock()

            mock_pool = mock_pool_cls.return_value
            mock_pool.can_fit = mock.AsyncMock(return_value=True)

            mock_credit = mock_credit_cls.return_value
            mock_credit.check_sufficient_credits = mock.AsyncMock(return_value=True)

            mock_vol = mock_vol_cls.return_value

            async def create_vol_side_effect(*, name, display_name, owner_id, max_size_bytes):
                vol = Volume(
                    name=name,
                    display_name=display_name,
                    owner_id=owner_id,
                    size_bytes=max_size_bytes or 1000,
                )
                db_session.add(vol)
                await db_session.commit()
                await db_session.refresh(vol)
                return vol

            mock_vol.create_volume = mock.AsyncMock(side_effect=create_vol_side_effect)
            mock_vol.record_mount = mock.AsyncMock()
            mock_vol.mark_home_volume = mock.AsyncMock()
            mock_vol.check_volumes_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol._parse_memory = mock.Mock(return_value=10737418240)

            mock_access = mock_access_cls.return_value
            mock_access.can_access_volume = mock.AsyncMock(return_value=True)

            yield

    return _stack()


class TestCreateServerGpuAllocation:
    """Exclusive pool behavior of POST /api/servers/."""

    @pytest.mark.asyncio
    async def test_create_reserves_and_forwards_gpu_devices(
        self, client, user_token, test_user, db_session, gpu_plan_env, gpu_pool, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env

        captured = {}

        async def fake_spawn(**kwargs):
            captured.update(kwargs)
            return Server(
                id=uuid_mod.UUID(kwargs["server_id"]),
                name=kwargs["server_name"],
                user_id=test_user.id,
                environment_id=env.id,
                container_id="container-gpu",
                image=env.image,
                status="running",
                allocated_cpu=plan.cpu_limit,
                allocated_memory=plan.memory_limit,
                allocated_disk=plan.disk_limit,
                allocated_gpu=plan.gpu_limit,
                external_url="http://test/url",
            )

        ctx = _create_server_mocks(db_session, fake_spawn)
        with ctx:
            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "gpu-server",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                },
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert captured["gpu"] == 1
        assert captured["gpu_devices"] == ["nvidia.com/gpu=0"]

        result = await db_session.execute(select(func.count()).select_from(GpuAllocation))
        assert result.scalar() == 1

    @pytest.mark.asyncio
    async def test_create_releases_allocation_when_spawn_fails(
        self, client, user_token, test_user, db_session, gpu_plan_env, gpu_pool, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env

        ctx = _create_server_mocks(db_session, Exception("spawn boom"))
        with ctx:
            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "gpu-server",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                },
            )

        assert response.status_code == 500, f"Response: {response.text}"

        # The reservation made before spawning must be gone.
        result = await db_session.execute(select(func.count()).select_from(GpuAllocation))
        assert result.scalar() == 0

    @pytest.mark.asyncio
    async def test_create_fails_with_429_when_pool_exhausted(
        self, client, user_token, test_user, db_session, gpu_plan_env, gpu_pool, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_enabled", True)
        plan, env = gpu_plan_env

        # Occupy the only device (pool has 2, occupy both via two servers).
        allocator = GpuAllocatorService(db_session)
        assert await allocator.allocate(str(uuid_mod.uuid4()), 2) is not None

        ctx = _create_server_mocks(db_session, Exception("should not be called"))
        with ctx:
            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "gpu-server",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                },
            )

        assert response.status_code == 429, f"Response: {response.text}"
        assert "No GPUs available" in response.json()["detail"]
