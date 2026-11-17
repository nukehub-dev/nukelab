# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Additional coverage tests for app.api.servers.

Targets helper functions and error/edge branches not exercised by the other
servers test modules: expiry preference parsing, GPU device ensure/release,
respawn helper, status-sync branches, start/stop/restart/delete error paths,
create volume variants, patch GPU re-reservation, logs since parsing, and
test-metric/access-token failure paths.
"""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.api.servers import (
    _audit_cross_user_access,
    _ensure_gpu_devices,
    _release_gpu_devices,
    _server_gpu_count,
    _set_server_expiry,
    spawner,
)
from app.config import settings
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.server_volume import ServerVolume
from app.models.volume import Volume


def _unique(prefix):
    return f"{prefix}-{uuid_mod.uuid4().hex[:8]}"


def _make_plan(**overrides):
    defaults = {
        "id": uuid_mod.uuid4(),
        "name": _unique("cov-plan"),
        "slug": _unique("cov-plan"),
        "cpu_limit": 1.0,
        "memory_limit": "1g",
        "disk_limit": "10g",
        "cost_per_hour": 0,
        "is_active": True,
        "is_public": True,
        "visible_to_roles": ["user"],
    }
    defaults.update(overrides)
    return ServerPlan(**defaults)


def _make_env(**overrides):
    defaults = {
        "id": uuid_mod.uuid4(),
        "name": _unique("cov-env"),
        "slug": _unique("cov-env"),
        "image": "test:latest",
    }
    defaults.update(overrides)
    return EnvironmentTemplate(**defaults)


def _mock_spawn_result(container_id="new-cid"):
    m = mock.Mock()
    m.container_id = container_id
    m.image = "test:latest"
    m.volume_id = None
    m.external_url = "http://test"
    m.allocated_cpu = 1.0
    m.allocated_memory = "1g"
    return m


@pytest_asyncio.fixture
async def cov_plan_env(db_session):
    plan = _make_plan()
    env = _make_env()
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)
    return plan, env


@pytest_asyncio.fixture
async def cov_server(db_session, test_user, cov_plan_env):
    plan, env = cov_plan_env
    server = Server(
        name=_unique("cov-srv"),
        user_id=test_user.id,
        status="stopped",
        plan_id=plan.id,
        environment_id=env.id,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


# ── Helper: _set_server_expiry ───────────────────────────────────────────────


class TestSetServerExpiry:
    """Branches of the max_server_runtime preference parser."""

    def test_invalid_preference_falls_back_to_default(self):
        server = mock.Mock()
        user = mock.Mock(preferences={"max_server_runtime": "not-a-number"})
        _set_server_expiry(server, user)
        expected = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=settings.server_max_runtime
        )
        assert abs((server.expires_at - expected).total_seconds()) < 5

    def test_zero_runtime_disables_expiry(self):
        server = mock.Mock()
        user = mock.Mock(preferences={"max_server_runtime": 0})
        _set_server_expiry(server, user)
        assert server.expires_at is None

    def test_disabled_runtime_clears_expiry(self):
        server = mock.Mock()
        user = mock.Mock(preferences={"max_server_runtime_enabled": False})
        _set_server_expiry(server, user)
        assert server.expires_at is None

    def test_missing_preference_uses_default(self):
        server = mock.Mock()
        user = mock.Mock(preferences={})
        _set_server_expiry(server, user)
        assert server.expires_at is not None


# ── Helper: GPU device accounting ────────────────────────────────────────────


class TestGpuHelpers:
    """_server_gpu_count, _ensure_gpu_devices, _release_gpu_devices."""

    def test_gpu_count_prefers_plan_limit(self):
        server = mock.Mock(allocated_gpu=5)
        plan = mock.Mock(gpu_limit=2)
        assert _server_gpu_count(server, plan) == 2

    def test_gpu_count_falls_back_to_allocation(self):
        server = mock.Mock(allocated_gpu=3)
        assert _server_gpu_count(server, None) == 3

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_disabled_returns_none(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            mock_alloc_cls.return_value.enabled = mock.Mock(return_value=False)
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 2)
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_zero_count_returns_none(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            mock_alloc_cls.return_value.enabled = mock.Mock(return_value=True)
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_reuses_existing_reservation(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=["nvidia.com/gpu=0"])
            alloc.allocate = mock.AsyncMock()
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert result == ["nvidia.com/gpu=0"]
        alloc.allocate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_allocates_when_missing(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=[])
            alloc.allocate = mock.AsyncMock(return_value=["nvidia.com/gpu=1"])
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert result == ["nvidia.com/gpu=1"]

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_exhausted_raises_429(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=[])
            alloc.allocate = mock.AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc_info:
                await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_release_gpu_devices_swallows_errors(self):
        with mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.release = mock.AsyncMock(side_effect=Exception("db down"))
            # Must not raise.
            await _release_gpu_devices(mock.AsyncMock(), "sid")


# ── Helper: _respawn_server_container ────────────────────────────────────────


class TestRespawnServerContainer:
    """The shared respawn helper used by scheduled/bulk/health-driven starts."""

    def _make_server(self, container_id="stale-cid"):
        server = mock.Mock()
        server.id = uuid_mod.uuid4()
        server.user_id = uuid_mod.uuid4()
        server.environment_id = uuid_mod.uuid4()
        server.plan_id = uuid_mod.uuid4()
        server.name = "respawn-srv"
        server.container_id = container_id
        server.allocated_cpu = 1.0
        server.allocated_memory = "1g"
        server.allocated_disk = "10g"
        server.allocated_gpu = 0
        return server


# ── Helper: _audit_cross_user_access ─────────────────────────────────────────


class TestAuditCrossUserAccess:
    @pytest.mark.asyncio
    async def test_same_user_is_noop(self):
        user_id = uuid_mod.uuid4()
        server = mock.Mock(user_id=user_id)
        current_user = mock.Mock(id=user_id)
        with mock.patch("app.services.activity_service.ActivityService") as mock_act_cls:
            await _audit_cross_user_access(server, current_user, mock.AsyncMock(), "server.x")
        mock_act_cls.assert_not_called()


# ── GET /api/servers/ status sync ────────────────────────────────────────────


class TestListServersStatusSync:
    @pytest.mark.asyncio
    async def test_list_syncs_stopped_server_to_running(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("list-sync"),
            user_id=test_user.id,
            status="stopped",
            container_id="cid-list",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        servers = response.json()["servers"]
        entry = next(s for s in servers if s["id"] == str(server.id))
        assert entry["status"] == "running"
        assert entry["started_at"] is not None

    @pytest.mark.asyncio
    async def test_list_syncs_running_server_to_stopped(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("list-sync2"),
            user_id=test_user.id,
            status="running",
            container_id="cid-list2",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            response = await client.get(
                "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        servers = response.json()["servers"]
        entry = next(s for s in servers if s["id"] == str(server.id))
        assert entry["status"] == "stopped"
        assert entry["stopped_at"] is not None

    @pytest.mark.asyncio
    async def test_list_status_check_error_is_swallowed(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("list-err"),
            user_id=test_user.id,
            status="running",
            container_id="cid-list3",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        servers = response.json()["servers"]
        entry = next(s for s in servers if s["id"] == str(server.id))
        assert entry["status"] == "running"

    @pytest.mark.asyncio
    async def test_list_admin_sees_other_users_servers(
        self, client, admin_token, test_user, db_session
    ):
        server = Server(
            name=_unique("list-admin"),
            user_id=test_user.id,
            status="stopped",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {admin_token}"}
        )

        assert response.status_code == 200
        servers = response.json()["servers"]
        assert any(s["id"] == str(server.id) for s in servers)


# ── GET /api/servers/{id} status sync ────────────────────────────────────────


class TestGetServerStatusSync:
    @pytest.mark.asyncio
    async def test_get_syncs_to_running_and_clears_stop_fields(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("get-sync"),
            user_id=test_user.id,
            status="stopped",
            container_id="cid-get",
            stop_reason="idle timeout",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["stop_reason"] is None
        assert data["started_at"] is not None

    @pytest.mark.asyncio
    async def test_get_syncs_to_stopped(self, client, user_token, test_user, db_session):
        server = Server(
            name=_unique("get-sync2"),
            user_id=test_user.id,
            status="running",
            container_id="cid-get2",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="exited"):
            response = await client.get(
                f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"
        assert data["stopped_at"] is not None

    @pytest.mark.asyncio
    async def test_get_status_error_is_swallowed(self, client, user_token, test_user, db_session):
        server = Server(
            name=_unique("get-err"),
            user_id=test_user.id,
            status="running",
            container_id="cid-get3",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "running"


# ── GET /api/servers/by-path/{username}/{name} ───────────────────────────────


class TestGetServerByPath:
    @pytest.mark.asyncio
    async def test_by_path_success_and_status_sync(self, client, user_token, test_user, db_session):
        server = Server(
            name="bypath-srv",
            user_id=test_user.id,
            status="stopped",
            container_id="cid-bypath",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/bypath-srv",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(server.id)
        assert data["status"] == "running"
        assert data["username"] == test_user.username

    @pytest.mark.asyncio
    async def test_by_path_cross_user_denied(self, client, user_token, admin_user, db_session):
        server = Server(
            name="bypath-admin-srv",
            user_id=admin_user.id,
            status="running",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()

        response = await client.get(
            f"/api/servers/by-path/{admin_user.username}/bypath-admin-srv",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_by_path_status_error_swallowed(self, client, user_token, test_user, db_session):
        server = Server(
            name="bypath-err-srv",
            user_id=test_user.id,
            status="running",
            container_id="cid-bypath-err",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", side_effect=Exception("docker down")):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/bypath-err-srv",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "running"


# ── POST /api/servers/ create variants ───────────────────────────────────────


class TestCreateServerCoverage:
    @pytest.mark.asyncio
    async def test_create_with_legacy_volume_id(
        self, client, user_token, test_user, db_session, cov_plan_env, server_api_runtime
    ):
        """Legacy selection preserves the existing private home volume and privacy label."""
        plan, env = cov_plan_env
        owner_id, username = test_user.id, test_user.username
        plan_id, env_id = plan.id, env.id
        volume = Volume(
            name=_unique("legacy-vol"),
            display_name="Legacy Vol",
            owner_id=owner_id,
            size_bytes=1000,
            max_size_bytes=1024**3,
            visibility="private",
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        volume_id, volume_name = volume.id, volume.name
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "legacy-srv",
                "plan_id": str(plan_id),
                "environment_id": str(env_id),
                "volume_id": str(volume_id),
                "volume_mode": "read_write",
            },
        )
        assert response.status_code == 200, response.text
        mounts = response.json()["volume_mounts"]
        assert len(mounts) == 1 and mounts[0]["volume_id"] == str(volume_id)
        assert mounts[0]["mount_path"] == f"/home/{username}"
        assert mounts[0]["mode"] == "read_write" and mounts[0]["is_primary"]
        runtime_mount = server_api_runtime.create_container.call_args.kwargs["volumes"][volume_name]
        assert runtime_mount == {"bind": f"/home/{username}", "mode": "rw"}
        current = await db_session.get(Volume, volume_id, populate_existing=True)
        assert current.labels["was_home_volume"] is True
        assert current.size_bytes == 1000

    @pytest.mark.asyncio
    async def test_create_with_multiple_auto_created_volumes(
        self, client, user_token, test_user, db_session, cov_plan_env, server_api_runtime
    ):
        """Distinct bounded auto-create intents retain their paths, modes and size ceilings."""
        from sqlalchemy import select

        plan, env = cov_plan_env
        owner_id, plan_id, env_id = test_user.id, plan.id, env.id
        requested = [
            {
                "volume_id": "",
                "mount_path": "/data",
                "mode": "read_write",
                "max_size_bytes": 1024**3,
            },
            {
                "volume_id": "",
                "mount_path": "/extra",
                "mode": "read_only",
                "max_size_bytes": 2 * 1024**3,
            },
        ]
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "multi-vol-srv",
                "plan_id": str(plan_id),
                "environment_id": str(env_id),
                "volume_mounts": requested,
            },
        )
        assert response.status_code == 200, response.text
        returned = response.json()["volume_mounts"]
        assert len(returned) == 2 and len({mount["volume_id"] for mount in returned}) == 2
        by_path = {mount["mount_path"]: mount for mount in returned}
        assert by_path["/data"]["is_primary"] and not by_path["/extra"]["is_primary"]
        volumes = list(await db_session.scalars(select(Volume).where(Volume.owner_id == owner_id)))
        assert len(volumes) == 2 and len({volume.name for volume in volumes}) == 2
        by_id = {str(volume.id): volume for volume in volumes}
        runtime_mounts = server_api_runtime.create_container.call_args.kwargs["volumes"]
        for intent in requested:
            mounted = by_path[intent["mount_path"]]
            volume = by_id[mounted["volume_id"]]
            assert (
                volume.visibility == "private" and volume.max_size_bytes == intent["max_size_bytes"]
            )
            assert mounted["mode"] == intent["mode"]
            assert runtime_mounts[volume.name] == {
                "bind": intent["mount_path"],
                "mode": "ro" if intent["mode"] == "read_only" else "rw",
            }

    @pytest.mark.asyncio
    async def test_create_volume_access_denied_read_only_label(
        self, client, user_token, admin_user, db_session, cov_plan_env, server_api_runtime
    ):
        """Read-only selection grants no access to another owner's private volume."""
        plan, env = cov_plan_env
        plan_id, env_id = plan.id, env.id
        volume = Volume(
            name=_unique("denied-vol"),
            display_name="Private data",
            owner_id=admin_user.id,
            size_bytes=1000,
            max_size_bytes=1024**3,
            visibility="private",
            status="active",
        )
        db_session.add(volume)
        await db_session.commit()
        volume_id = volume.id
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "denied-srv",
                "plan_id": str(plan_id),
                "environment_id": str(env_id),
                "volume_mounts": [
                    {"volume_id": str(volume_id), "mount_path": "/data", "mode": "read_only"}
                ],
            },
        )
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "volume_unavailable"
        server_api_runtime.create_container.assert_not_awaited()
        assert (await db_session.get(Volume, volume_id, populate_existing=True)).size_bytes == 1000

    @pytest.mark.asyncio
    async def test_create_volume_quota_exceeded(
        self, client, user_token, test_user, db_session, cov_plan_env, server_api_runtime
    ):
        """Mount capacity is bounded by the plan across the complete selection."""
        plan, env = cov_plan_env
        plan_id, env_id, owner_id = plan.id, env.id, test_user.id
        volumes = [
            Volume(
                name=_unique("quota-vol"),
                display_name="Selected data",
                owner_id=owner_id,
                size_bytes=1000,
                max_size_bytes=6 * 1024**3,
                visibility="private",
                status="active",
            )
            for _ in range(2)
        ]
        db_session.add_all(volumes)
        await db_session.commit()
        identifiers = [str(volume.id) for volume in volumes]
        response = await client.post(
            "/api/servers/",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "name": "quota-srv",
                "plan_id": str(plan_id),
                "environment_id": str(env_id),
                "volume_mounts": [
                    {"volume_id": identifier, "mount_path": f"/data{index}", "mode": "read_write"}
                    for index, identifier in enumerate(identifiers)
                ],
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "volume_capacity_exceeded"
        server_api_runtime.create_container.assert_not_awaited()


# ── POST /{id}/start branches ────────────────────────────────────────────────


# ── POST /{id}/stop branches ─────────────────────────────────────────────────


class TestStopServerCoverage:
    @pytest.mark.asyncio
    async def test_stop_without_container_preserves_unverified_allocation(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.status = "running"
        cov_server.container_id = None
        await db_session.commit()
        identifier = cov_server.id
        cpu = cov_server.allocated_cpu

        response = await client.post(
            f"/api/servers/{identifier}/stop",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "recovery_required"
        current = await db_session.get(Server, identifier, populate_existing=True)
        assert current.status == "stopping" and current.allocated_cpu == cpu


# ── POST /{id}/restart branches ──────────────────────────────────────────────


# ── DELETE /{id} branches ────────────────────────────────────────────────────


# ── PATCH /{id} GPU re-reservation + misc ────────────────────────────────────


# ── POST /{id}/test-metric failure ───────────────────────────────────────────


class TestTestMetricCoverage:
    @pytest.mark.asyncio
    async def test_publish_failure_returns_500(self, client, user_token, cov_server):
        with mock.patch("app.core.redis_client.get_redis_client") as mock_redis_fn:
            mock_r = mock.AsyncMock()
            mock_r.publish = mock.AsyncMock(side_effect=Exception("redis down"))
            mock_redis_fn.return_value = mock_r

            response = await client.post(
                f"/api/servers/{cov_server.id}/test-metric",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "Failed to publish test metric" in response.json()["detail"]


# ── GET /{id}/logs branches ──────────────────────────────────────────────────


class TestServerLogsCoverage:
    @pytest.mark.asyncio
    async def test_logs_with_since_param(self, client, user_token, test_user, db_session):
        server = Server(
            name=_unique("logs-since"),
            user_id=test_user.id,
            status="running",
            container_id="cid-since",
        )
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.AsyncMock()
        mock_client.get_container_logs = mock.AsyncMock(return_value="some logs")
        original = spawner.container_client
        spawner.container_client = mock_client
        try:
            response = await client.get(
                f"/api/servers/{server.id}/logs?since=2024-01-01T00:00:00Z&tail=50",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        finally:
            spawner.container_client = original

        assert response.status_code == 200
        kwargs = mock_client.get_container_logs.call_args.kwargs
        assert kwargs["since"] == int(datetime(2024, 1, 1, tzinfo=UTC).timestamp())
        assert kwargs["tail"] == 50

    @pytest.mark.asyncio
    async def test_logs_invalid_since_is_ignored(self, client, user_token, test_user, db_session):
        server = Server(
            name=_unique("logs-bad-since"),
            user_id=test_user.id,
            status="running",
            container_id="cid-bad-since",
        )
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.AsyncMock()
        mock_client.get_container_logs = mock.AsyncMock(return_value="some logs")
        original = spawner.container_client
        spawner.container_client = mock_client
        try:
            response = await client.get(
                f"/api/servers/{server.id}/logs?since=not-a-timestamp",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        finally:
            spawner.container_client = original

        assert response.status_code == 200
        assert mock_client.get_container_logs.call_args.kwargs["since"] is None

    @pytest.mark.asyncio
    async def test_logs_unexpected_error_returns_500(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("logs-err"),
            user_id=test_user.id,
            status="running",
            container_id="cid-logs-err",
        )
        db_session.add(server)
        await db_session.commit()

        mock_client = mock.AsyncMock()
        mock_client.get_container_logs = mock.AsyncMock(side_effect=RuntimeError("unexpected"))
        original = spawner.container_client
        spawner.container_client = mock_client
        try:
            response = await client.get(
                f"/api/servers/{server.id}/logs",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        finally:
            spawner.container_client = original

        assert response.status_code == 500
        assert "Failed to retrieve logs" in response.json()["detail"]


# ── POST /{id}/access-token failure ──────────────────────────────────────────


class TestAccessTokenCoverage:
    @pytest.mark.asyncio
    async def test_access_token_unexpected_error_returns_500(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.server_auth_service.server_auth_service") as mock_svc:
            mock_svc.is_enabled = True
            mock_svc.generate_access_token = mock.AsyncMock(
                side_effect=RuntimeError("token store down")
            )
            response = await client.post(
                f"/api/servers/{cov_server.id}/access-token",
                headers={"Authorization": f"Bearer {user_token}"},
                json={},
            )

        assert response.status_code == 500
        assert "Failed to generate access token" in response.json()["detail"]


# ── Remaining branch mop-up ──────────────────────────────────────────────────


class TestAdminListCacheKey:
    """_admin_server_list_cache_key is a module-level helper (dead in this
    module, kept for parity with admin.py)."""

    def test_key_includes_all_params(self):
        from app.api.servers import _admin_server_list_cache_key

        assert (
            _admin_server_list_cache_key(2, 25, "running", "u1")
            == "servers:list:admin:2:25:running:u1"
        )
        assert _admin_server_list_cache_key(1, 10, None, None) == "servers:list:admin:1:10:all:all"


class TestCreateInactivePlanBranch:
    @pytest.mark.asyncio
    async def test_create_inactive_plan_returns_400(
        self, client, user_token, db_session, cov_plan_env
    ):
        """Plan usable but inactive -> 400 (line 446)."""
        _, env = cov_plan_env
        plan_id = uuid_mod.uuid4()
        fake_plan = mock.Mock()
        fake_plan.id = plan_id
        fake_plan.is_active = False

        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=fake_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)

            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "inactive-plan-srv",
                    "plan_id": str(plan_id),
                    "environment_id": str(env.id),
                },
            )

        assert response.status_code == 400
        assert "not active" in response.json()["detail"].lower()


class TestListServersVolumeMountSerialization:
    @pytest.mark.asyncio
    async def test_list_serializes_volume_mounts(self, client, user_token, test_user, db_session):
        """Servers with mounts exercise _serialize_volume_mounts (line 363)."""
        volume = Volume(
            name=_unique("list-ser-vol"),
            display_name="List Ser Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        server = Server(
            name=_unique("list-ser-srv"),
            user_id=test_user.id,
            status="stopped",
            container_id=None,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)
        db_session.add(
            ServerVolume(
                server_id=server.id,
                volume_id=volume.id,
                mount_path="/data",
                mode="read_write",
                is_primary=True,
            )
        )
        await db_session.commit()

        response = await client.get(
            "/api/servers/", headers={"Authorization": f"Bearer {user_token}"}
        )

        assert response.status_code == 200
        entry = next(s for s in response.json()["servers"] if s["id"] == str(server.id))
        assert len(entry["volume_mounts"]) == 1
        assert entry["volume_mounts"][0]["volume_id"] == str(volume.id)
        assert entry["volume_mounts"][0]["volume"]["name"] == volume.name


class TestStartStopRestartMopUp:
    @pytest.mark.asyncio
    async def test_restart_gpu_ensure_failure_propagates(
        self, client, user_token, cov_server, cov_plan_env, db_session
    ):
        """HTTPException inside the restart try-block re-raises (line 1507)."""
        plan, _ = cov_plan_env
        plan.gpu_limit = 1
        cov_server.container_id = "cid-gpu-restart-429"
        cov_server.status = "running"
        cov_server.allocated_gpu = 1
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls,
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.delete", new=mock.AsyncMock()),
            mock.patch(
                "app.api.servers._ensure_gpu_devices",
                new=mock.AsyncMock(side_effect=HTTPException(status_code=429, detail="no gpu")),
            ),
        ):
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)

            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 429
