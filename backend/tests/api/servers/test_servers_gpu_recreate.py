# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""GPU servers must recreate (never plain-start) containers in exclusive mode.

A stopped container keeps its original GPU DeviceRequests baked in. When the
exclusive allocator is enabled, start-class paths must route GPU servers
through spawner.spawn (recreate with the devices they currently own) instead
of container.start on the stale container. Non-GPU servers and
allocator-disabled mode keep the cheap plain-start behavior.
"""

import uuid as uuid_mod
from unittest import mock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.config import settings
from app.models.environment_template import EnvironmentTemplate
from app.models.gpu_allocation import GpuAllocation
from app.models.server import Server
from app.models.server_plan import ServerPlan

POOL = "nvidia.com/gpu=0,nvidia.com/gpu=1"


def _mock_spawn_server():
    new = mock.AsyncMock()
    new.container_id = "new-cid"
    new.image = "test:latest"
    new.volume_id = None
    new.external_url = "http://test"
    new.allocated_cpu = 1.0
    new.allocated_memory = "1g"
    return new


@pytest_asyncio.fixture
async def gpu_plan_env(db_session):
    plan = ServerPlan(
        name=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-plan-{uuid_mod.uuid4().hex[:8]}",
        cpu_limit=1,
        memory_limit="1g",
        disk_limit="10g",
        gpu_limit=1,
        is_public=True,
        is_active=True,
        cost_per_hour=0,
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(
        name=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        slug=f"gpu-env-{uuid_mod.uuid4().hex[:8]}",
        image="test:latest",
    )
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)
    return plan, env


@pytest_asyncio.fixture
async def gpu_server(db_session, test_user, gpu_plan_env):
    plan, env = gpu_plan_env
    server = Server(
        name="gpu-srv",
        user_id=test_user.id,
        status="stopped",
        container_id="old-cid",
        plan_id=plan.id,
        environment_id=env.id,
        allocated_gpu=1,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


@pytest_asyncio.fixture
async def plain_server(db_session, test_user, gpu_plan_env):
    """Non-GPU server on a GPU-less plan."""
    plan, env = gpu_plan_env
    plan.gpu_limit = 0
    await db_session.commit()
    server = Server(
        name="plain-srv",
        user_id=test_user.id,
        status="stopped",
        container_id="old-cid",
        plan_id=plan.id,
        environment_id=env.id,
        allocated_gpu=0,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


class TestGpuStartForcesRecreate:
    """POST /start with an existing (paused/stopped) container."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("container_status", ["paused", "stopped"])
    async def test_gpu_server_start_recreates_container(
        self, client, user_token, db_session, gpu_server, container_status, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_devices", POOL)
        mock_spawn = _mock_spawn_server()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch(
                "app.api.servers.spawner.get_status", return_value=container_status
            ) as mock_get_status,
            mock.patch("app.api.servers.spawner.delete") as mock_delete,
            mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn) as mock_spawn_fn,
            mock.patch("app.api.servers.spawner.start") as mock_start,
        ):
            response = await client.post(
                f"/api/servers/{gpu_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"

        # Recreate path: stale container deleted, fresh spawn with ensured
        # devices, never a plain container.start.
        mock_get_status.assert_called_once_with("old-cid")
        mock_delete.assert_called_once_with("old-cid")
        mock_spawn_fn.assert_called_once()
        assert mock_spawn_fn.call_args.kwargs["gpu_devices"] == ["nvidia.com/gpu=0"]
        assert mock_spawn_fn.call_args.kwargs["server_id"] == str(gpu_server.id)
        mock_start.assert_not_called()

        # The reservation is held by the server after recreate.
        result = await db_session.execute(
            select(GpuAllocation.device).where(GpuAllocation.server_id == gpu_server.id)
        )
        assert result.scalars().all() == ["nvidia.com/gpu=0"]

    @pytest.mark.asyncio
    async def test_non_gpu_server_still_plain_starts(
        self, client, user_token, db_session, plain_server, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_devices", POOL)

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.delete") as mock_delete,
            mock.patch("app.api.servers.spawner.spawn") as mock_spawn_fn,
            mock.patch("app.api.servers.spawner.start", return_value=True) as mock_start,
        ):
            response = await client.post(
                f"/api/servers/{plain_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"
        mock_start.assert_called_once_with("old-cid")
        mock_spawn_fn.assert_not_called()
        mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_allocator_disabled_gpu_server_still_plain_starts(
        self, client, user_token, db_session, gpu_server, monkeypatch
    ):
        # Legacy shared mode: no pool configured, so no recreate is forced
        # even though the server has allocated_gpu > 0.
        monkeypatch.setattr(settings, "gpu_devices", "")

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.delete") as mock_delete,
            mock.patch("app.api.servers.spawner.spawn") as mock_spawn_fn,
            mock.patch("app.api.servers.spawner.start", return_value=True) as mock_start,
        ):
            response = await client.post(
                f"/api/servers/{gpu_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"
        mock_start.assert_called_once_with("old-cid")
        mock_spawn_fn.assert_not_called()
        mock_delete.assert_not_called()


class TestGpuRestartForcesRecreate:
    """POST /restart routes GPU servers to recreate instead of stop+start."""

    @pytest.mark.asyncio
    async def test_gpu_server_restart_recreates_and_reuses_devices(
        self, client, user_token, db_session, gpu_server, monkeypatch
    ):
        monkeypatch.setattr(settings, "gpu_devices", POOL)
        gpu_server.status = "running"
        # The server's rows are still reserved (no release on restart); the
        # recreate must reuse device 1 rather than grabbing device 0.
        db_session.add(GpuAllocation(server_id=gpu_server.id, device="nvidia.com/gpu=1"))
        await db_session.commit()

        mock_spawn = _mock_spawn_server()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.delete") as mock_delete,
            mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn) as mock_spawn_fn,
            mock.patch("app.api.servers.spawner.start") as mock_start,
            mock.patch("app.api.servers.spawner.stop") as mock_stop,
        ):
            response = await client.post(
                f"/api/servers/{gpu_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"

        mock_delete.assert_called_once_with("old-cid")
        mock_spawn_fn.assert_called_once()
        assert mock_spawn_fn.call_args.kwargs["gpu_devices"] == ["nvidia.com/gpu=1"]
        mock_start.assert_not_called()
        mock_stop.assert_not_called()

        # The pre-existing reservation survived the restart untouched.
        result = await db_session.execute(
            select(GpuAllocation.device).where(GpuAllocation.server_id == gpu_server.id)
        )
        assert result.scalars().all() == ["nvidia.com/gpu=1"]
