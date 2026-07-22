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
    _respawn_server_container,
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
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
            mock_alloc_cls.return_value.enabled = mock.Mock(return_value=False)
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 2)
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_zero_count_returns_none(self):
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
            mock_alloc_cls.return_value.enabled = mock.Mock(return_value=True)
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_reuses_existing_reservation(self):
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=["nvidia.com/gpu=0"])
            alloc.allocate = mock.AsyncMock()
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert result == ["nvidia.com/gpu=0"]
        alloc.allocate.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_allocates_when_missing(self):
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=[])
            alloc.allocate = mock.AsyncMock(return_value=["nvidia.com/gpu=1"])
            result = await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert result == ["nvidia.com/gpu=1"]

    @pytest.mark.asyncio
    async def test_ensure_gpu_devices_exhausted_raises_429(self):
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=[])
            alloc.allocate = mock.AsyncMock(return_value=None)
            with pytest.raises(HTTPException) as exc_info:
                await _ensure_gpu_devices(mock.AsyncMock(), "sid", 1)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_release_gpu_devices_swallows_errors(self):
        with mock.patch(
            "app.services.gpu_allocator.GpuAllocatorService"
        ) as mock_alloc_cls:
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

    @pytest.mark.asyncio
    async def test_respawn_deletes_stale_container_and_spawns(self):
        server = self._make_server()
        owner = mock.Mock(username="owneruser")
        db = mock.AsyncMock()
        db.execute.return_value.scalar_one_or_none = mock.Mock(return_value=owner)

        env = mock.Mock(slug="dev", image="img:latest")
        plan = mock.Mock(cpu_limit=2.0, memory_limit="2g", disk_limit="20g", gpu_limit=0)
        new_server = mock.Mock()

        with (
            mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls,
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
            mock.patch(
                "app.api.servers._load_server_volume_mounts",
                new=mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                "app.api.servers._ensure_gpu_devices",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch(
                "app.api.servers.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("delete failed")),
            ) as mock_delete,
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=new_server),
            ) as mock_spawn,
        ):
            mock_env_cls.return_value.get_by_id = mock.AsyncMock(return_value=env)
            mock_plan_cls.return_value.get_by_id = mock.AsyncMock(return_value=plan)
            result = await _respawn_server_container(server, db, "fallback")

        # Stale container deletion failed but was swallowed; spawn still ran.
        mock_delete.assert_called_once_with("stale-cid")
        mock_spawn.assert_called_once()
        assert mock_spawn.call_args.kwargs["username"] == "owneruser"
        assert result is new_server

    @pytest.mark.asyncio
    async def test_respawn_without_container_uses_fallback_username(self):
        server = self._make_server(container_id=None)
        db = mock.AsyncMock()
        db.execute.return_value.scalar_one_or_none = mock.Mock(return_value=None)

        new_server = mock.Mock()

        with (
            mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls,
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
            mock.patch(
                "app.api.servers._load_server_volume_mounts",
                new=mock.AsyncMock(return_value=[]),
            ),
            mock.patch(
                "app.api.servers._ensure_gpu_devices",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch(
                "app.api.servers.spawner.delete", new=mock.AsyncMock()
            ) as mock_delete,
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=new_server),
            ) as mock_spawn,
        ):
            mock_env_cls.return_value.get_by_id = mock.AsyncMock(return_value=None)
            mock_plan_cls.return_value.get_by_id = mock.AsyncMock(return_value=None)
            result = await _respawn_server_container(server, db, "fallback-user")

        mock_delete.assert_not_called()
        assert mock_spawn.call_args.kwargs["username"] == "fallback-user"
        # No environment -> legacy "dev" slug fallback.
        assert mock_spawn.call_args.kwargs["environment"] == "dev"
        assert result is new_server


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

        with mock.patch(
            "app.api.servers.spawner.get_status", side_effect=Exception("docker down")
        ):
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

        with mock.patch("app.api.servers.spawner.get_status", return_value="paused"):
            response = await client.get(
                f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"
        assert data["stopped_at"] is not None

    @pytest.mark.asyncio
    async def test_get_status_error_is_swallowed(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name=_unique("get-err"),
            user_id=test_user.id,
            status="running",
            container_id="cid-get3",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch(
            "app.api.servers.spawner.get_status", side_effect=Exception("docker down")
        ):
            response = await client.get(
                f"/api/servers/{server.id}", headers={"Authorization": f"Bearer {user_token}"}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "running"


# ── GET /api/servers/by-path/{username}/{name} ───────────────────────────────


class TestGetServerByPath:
    @pytest.mark.asyncio
    async def test_by_path_success_and_status_sync(
        self, client, user_token, test_user, db_session
    ):
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
    async def test_by_path_cross_user_denied(
        self, client, user_token, admin_user, db_session
    ):
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
    async def test_by_path_status_error_swallowed(
        self, client, user_token, test_user, db_session
    ):
        server = Server(
            name="bypath-err-srv",
            user_id=test_user.id,
            status="running",
            container_id="cid-bypath-err",
        )
        db_session.add(server)
        await db_session.commit()

        with mock.patch(
            "app.api.servers.spawner.get_status", side_effect=Exception("docker down")
        ):
            response = await client.get(
                f"/api/servers/by-path/{test_user.username}/bypath-err-srv",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert response.json()["status"] == "running"


# ── POST /api/servers/ create variants ───────────────────────────────────────


def _create_stack_mocks(db_session, *, spawn_return=None, spawn_side_effect=None):
    """Context-manager stack mocking the services used by create_server."""
    import contextlib

    @contextlib.contextmanager
    def _stack():
        with (
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
            mock.patch(
                "app.services.resource_pool_service.ResourcePoolService"
            ) as mock_pool_cls,
            mock.patch("app.services.credit_service.CreditService") as mock_credit_cls,
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
            mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls,
        ):
            mock_quota = mock_quota_cls.return_value
            mock_quota.check_spawn_allowed = mock.AsyncMock(return_value={"allowed": True})
            mock_quota.increment_usage = mock.AsyncMock()
            mock_pool_cls.return_value.can_fit = mock.AsyncMock(return_value=True)
            mock_credit_cls.return_value.check_sufficient_credits = mock.AsyncMock(
                return_value=True
            )
            mock_vol = mock_vol_cls.return_value
            mock_vol.record_mount = mock.AsyncMock()
            mock_vol.mark_home_volume = mock.AsyncMock()
            mock_vol.check_volumes_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol._parse_memory = mock.Mock(return_value=10737418240)
            mock_access = mock_access_cls.return_value
            mock_access.can_access_volume = mock.AsyncMock(return_value=True)

            spawn_patch = mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(
                    return_value=spawn_return, side_effect=spawn_side_effect
                ),
            )
            with spawn_patch as mock_spawn:
                yield {
                    "quota": mock_quota,
                    "pool": mock_pool_cls.return_value,
                    "credit": mock_credit_cls.return_value,
                    "volume": mock_vol,
                    "access": mock_access,
                    "spawn": mock_spawn,
                }

    return _stack()


class TestCreateServerCoverage:
    @pytest.mark.asyncio
    async def test_create_with_legacy_volume_id(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        """Deprecated volume_id/volume_mode fields build a home-dir mount."""
        plan, env = cov_plan_env
        volume = Volume(
            name=_unique("legacy-vol"),
            display_name="Legacy Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        mock_server = Server(
            id=uuid_mod.uuid4(),
            name="legacy-srv",
            user_id=test_user.id,
            environment_id=env.id,
            container_id="cid-legacy",
            image=env.image,
            volume_id=volume.id,
            status="running",
            allocated_cpu=plan.cpu_limit,
            allocated_memory=plan.memory_limit,
            allocated_disk=plan.disk_limit,
        )

        with _create_stack_mocks(db_session, spawn_return=mock_server) as mocks:
            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "legacy-srv",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_id": str(volume.id),
                    "volume_mode": "read_write",
                },
            )

        assert response.status_code == 200, f"Response: {response.text}"
        spawn_kwargs = mocks["spawn"].call_args.kwargs
        assert spawn_kwargs["volume_mounts"] == [
            {
                "volume_id": str(volume.id),
                "mount_path": f"/home/{test_user.username}",
                "mode": "read_write",
                "is_primary": True,
            }
        ]
        # Home-directory mount is flagged for privacy warnings.
        mocks["volume"].mark_home_volume.assert_called_once_with(str(volume.id))

    @pytest.mark.asyncio
    async def test_create_with_multiple_auto_created_volumes(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        """Multiple empty volume_id mounts auto-create data/data-N volumes."""
        plan, env = cov_plan_env

        mock_server = Server(
            id=uuid_mod.uuid4(),
            name="multi-vol-srv",
            user_id=test_user.id,
            environment_id=env.id,
            container_id="cid-multi",
            image=env.image,
            volume_id=None,
            status="running",
            allocated_cpu=plan.cpu_limit,
            allocated_memory=plan.memory_limit,
            allocated_disk=plan.disk_limit,
        )

        with _create_stack_mocks(db_session, spawn_return=mock_server) as mocks:
            created_names = []

            async def create_vol_side_effect(*, name, display_name, owner_id, max_size_bytes):
                created_names.append(name)
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

            mocks["volume"].create_volume = mock.AsyncMock(side_effect=create_vol_side_effect)

            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "multi-vol-srv",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_mounts": [
                        {"volume_id": "", "mount_path": "/data", "mode": "read_write"},
                        {"volume_id": "", "mount_path": "/extra", "mode": "read_only"},
                    ],
                },
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert len(created_names) == 2
        assert created_names[0].endswith("-data")
        assert created_names[1].endswith("-data-1")
        data = response.json()
        assert len(data["volume_mounts"]) == 2
        # First mount is marked primary when none is specified.
        assert data["volume_mounts"][0]["is_primary"] is True

    @pytest.mark.asyncio
    async def test_create_volume_access_denied_read_only_label(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        plan, env = cov_plan_env
        volume = Volume(
            name=_unique("denied-vol"),
            display_name="Denied Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with _create_stack_mocks(db_session, spawn_return=mock.Mock()) as mocks:
            mocks["access"].can_access_volume = mock.AsyncMock(return_value=False)
            mocks["volume"].get_volume = mock.AsyncMock(return_value=volume)

            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "denied-srv",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_mounts": [
                        {
                            "volume_id": str(volume.id),
                            "mount_path": "/data",
                            "mode": "read_only",
                        }
                    ],
                },
            )

        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_volume_quota_exceeded(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        plan, env = cov_plan_env
        volume = Volume(
            name=_unique("quota-vol"),
            display_name="Quota Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with _create_stack_mocks(db_session, spawn_return=mock.Mock()) as mocks:
            mocks["volume"].check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": False, "reason": "aggregate quota exceeded"}
            )

            response = await client.post(
                "/api/servers/",
                headers={"Authorization": f"Bearer {user_token}"},
                json={
                    "name": "quota-srv",
                    "plan_id": str(plan.id),
                    "environment_id": str(env.id),
                    "volume_mounts": [
                        {
                            "volume_id": str(volume.id),
                            "mount_path": "/data",
                            "mode": "read_write",
                        }
                    ],
                },
            )

        assert response.status_code == 400
        assert "aggregate quota exceeded" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_gpu_pool_exhausted_returns_429(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        plan, env = cov_plan_env
        plan.gpu_limit = 1
        await db_session.commit()

        volume = Volume(
            name=_unique("gpu-vol"),
            display_name="Gpu Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with _create_stack_mocks(db_session, spawn_return=mock.Mock()):
            with mock.patch(
                "app.services.gpu_allocator.GpuAllocatorService"
            ) as mock_alloc_cls:
                alloc = mock_alloc_cls.return_value
                alloc.enabled = mock.Mock(return_value=True)
                alloc.devices_for = mock.AsyncMock(return_value=[])
                alloc.allocate = mock.AsyncMock(return_value=None)

                response = await client.post(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "name": "gpu-srv",
                        "plan_id": str(plan.id),
                        "environment_id": str(env.id),
                        "volume_mounts": [
                            {
                                "volume_id": str(volume.id),
                                "mount_path": "/data",
                                "mode": "read_write",
                            }
                        ],
                    },
                )

        assert response.status_code == 429
        assert "No GPUs available" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_spawn_failure_releases_gpu_devices(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        plan, env = cov_plan_env
        plan.gpu_limit = 1
        await db_session.commit()

        volume = Volume(
            name=_unique("gpu-vol2"),
            display_name="Gpu Vol 2",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with _create_stack_mocks(db_session, spawn_side_effect=Exception("boom")):
            with (
                mock.patch(
                    "app.services.gpu_allocator.GpuAllocatorService"
                ) as mock_alloc_cls,
                mock.patch(
                    "app.container.client.get_container_client",
                    new=mock.AsyncMock(return_value=mock.AsyncMock()),
                ),
            ):
                alloc = mock_alloc_cls.return_value
                alloc.enabled = mock.Mock(return_value=True)
                alloc.devices_for = mock.AsyncMock(return_value=[])
                alloc.allocate = mock.AsyncMock(return_value=["nvidia.com/gpu=0"])
                alloc.release = mock.AsyncMock()

                response = await client.post(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "name": "gpu-fail-srv",
                        "plan_id": str(plan.id),
                        "environment_id": str(env.id),
                        "volume_mounts": [
                            {
                                "volume_id": str(volume.id),
                                "mount_path": "/data",
                                "mode": "read_write",
                            }
                        ],
                    },
                )

        assert response.status_code == 500
        # The reserved device must be freed when the spawn fails.
        alloc.release.assert_called_once()


# ── POST /{id}/start branches ────────────────────────────────────────────────


class TestStartServerCoverage:
    @pytest.mark.asyncio
    async def test_start_plain_start_failure_returns_500(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-plain"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.start", return_value=False),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "Failed to start server" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_plan_access_lost_returns_403(
        self, client, user_token, cov_server
    ):
        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
        ):
            mock_plan_cls.return_value.can_user_use_plan = mock.AsyncMock(return_value=False)
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 403
        assert "no longer available" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_insufficient_credits_returns_402(
        self, client, user_token, cov_server, cov_plan_env, db_session
    ):
        plan, _ = cov_plan_env
        plan.cost_per_hour = 10
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", True),
            mock.patch("app.services.credit_service.CreditService") as mock_credit_cls,
        ):
            mock_credit_cls.return_value.check_sufficient_credits = mock.AsyncMock(
                return_value=False
            )
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_start_volume_quota_exceeded_returns_400(
        self, client, user_token, test_user, cov_server, db_session
    ):
        volume = Volume(
            name=_unique("start-vol"),
            display_name="Start Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)
        db_session.add(
            ServerVolume(
                server_id=cov_server.id,
                volume_id=volume.id,
                mount_path="/data",
                mode="read_write",
                is_primary=True,
            )
        )
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
        ):
            mock_vol_cls.return_value.check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": False, "reason": "volume too big"}
            )
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "volume too big" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_plain_start_records_legacy_volume_mount(
        self, client, user_token, test_user, cov_server, db_session
    ):
        """Plain-start path records a mount for the legacy server.volume_id."""
        volume = Volume(
            name=_unique("legacy-mount-vol"),
            display_name="Legacy Mount Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        cov_server.container_id = "cid-legacy-start"
        cov_server.volume_id = volume.id
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch("app.api.servers.spawner.start", return_value=True),
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
        ):
            mock_vol_cls.return_value.record_mount = mock.AsyncMock()
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        mock_vol_cls.return_value.record_mount.assert_called_once_with(str(volume.id))

    @pytest.mark.asyncio
    async def test_start_stopped_container_delete_failure_is_swallowed(
        self, client, user_token, cov_server, db_session
    ):
        """A stopped container is deleted+recreated; delete errors are tolerated."""
        cov_server.container_id = "cid-stale"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="stopped"),
            mock.patch(
                "app.api.servers.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("delete failed")),
            ),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result("recreated-cid")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"
        assert "recreated" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_start_no_container_spawn_failure_returns_500(
        self, client, user_token, cov_server
    ):
        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(side_effect=Exception("spawn boom")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "Failed to restart server" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_no_container_records_volume_mounts(
        self, client, user_token, test_user, cov_server, db_session
    ):
        """Fresh-spawn start records mounts for each attached volume."""
        volume = Volume(
            name=_unique("spawn-mount-vol"),
            display_name="Spawn Mount Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)
        db_session.add(
            ServerVolume(
                server_id=cov_server.id,
                volume_id=volume.id,
                mount_path="/data",
                mode="read_write",
                is_primary=True,
            )
        )
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result()),
            ),
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
        ):
            mock_vol_cls.return_value.check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": True}
            )
            mock_vol_cls.return_value.record_mount = mock.AsyncMock()
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        mock_vol_cls.return_value.record_mount.assert_called_once_with(str(volume.id))


# ── POST /{id}/stop branches ─────────────────────────────────────────────────


class TestStopServerCoverage:
    @pytest.mark.asyncio
    async def test_stop_delete_failure_returns_500(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-stop-fail"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.spawner.get_status", return_value="running"),
            mock.patch(
                "app.api.servers.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("delete boom")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "Failed to stop server" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_stop_reconciles_billing_and_quota(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-stop-bill"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.spawner.get_status", return_value="running"),
            mock.patch("app.api.servers.spawner.delete", new=mock.AsyncMock()),
            mock.patch("app.services.credit_service.CreditService") as mock_credit_cls,
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
        ):
            mock_credit_cls.return_value.reconcile_server_billing = mock.AsyncMock()
            mock_quota_cls.return_value.decrement_usage = mock.AsyncMock()
            response = await client.post(
                f"/api/servers/{cov_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        mock_credit_cls.return_value.reconcile_server_billing.assert_called_once()
        mock_quota_cls.return_value.decrement_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_without_container_marks_stopped(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.status = "running"
        cov_server.container_id = None
        await db_session.commit()

        response = await client.post(
            f"/api/servers/{cov_server.id}/stop",
            headers={"Authorization": f"Bearer {user_token}"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "stopped"


# ── POST /{id}/restart branches ──────────────────────────────────────────────


class TestRestartServerCoverage:
    @pytest.mark.asyncio
    async def test_restart_without_container_returns_400(
        self, client, user_token, cov_server
    ):
        with mock.patch("app.api.servers.settings.credits_enabled", False):
            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "No container" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_restart_stop_failure_returns_500(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-restart-fail"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="running"),
            mock.patch(
                "app.api.servers.spawner.stop",
                new=mock.AsyncMock(side_effect=Exception("stop boom")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 500
        assert "Failed to restart server" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_restart_plan_access_lost_returns_403(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-restart-403"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
        ):
            mock_plan_cls.return_value.can_user_use_plan = mock.AsyncMock(return_value=False)
            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_restart_insufficient_credits_returns_402(
        self, client, user_token, cov_server, cov_plan_env, db_session
    ):
        plan, _ = cov_plan_env
        plan.cost_per_hour = 10
        cov_server.container_id = "cid-restart-402"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", True),
            mock.patch("app.services.credit_service.CreditService") as mock_credit_cls,
        ):
            mock_credit_cls.return_value.check_sufficient_credits = mock.AsyncMock(
                return_value=False
            )
            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 402

    @pytest.mark.asyncio
    async def test_restart_volume_quota_exceeded_returns_400(
        self, client, user_token, test_user, cov_server, db_session
    ):
        volume = Volume(
            name=_unique("restart-vol"),
            display_name="Restart Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)
        db_session.add(
            ServerVolume(
                server_id=cov_server.id,
                volume_id=volume.id,
                mount_path="/data",
                mode="read_write",
                is_primary=True,
            )
        )
        cov_server.container_id = "cid-restart-quota"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
        ):
            mock_vol_cls.return_value.check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": False, "reason": "restart quota"}
            )
            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 400
        assert "restart quota" in response.json()["detail"]


# ── DELETE /{id} branches ────────────────────────────────────────────────────


class TestDeleteServerCoverage:
    @pytest.mark.asyncio
    async def test_delete_container_failure_is_swallowed(
        self, client, user_token, cov_server, db_session
    ):
        cov_server.container_id = "cid-del-fail"
        await db_session.commit()

        with mock.patch(
            "app.api.servers.spawner.delete",
            new=mock.AsyncMock(side_effect=Exception("delete boom")),
        ):
            response = await client.delete(
                f"/api/servers/{cov_server.id}",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert response.json()["message"] == "Server deleted"


# ── PATCH /{id} GPU re-reservation + misc ────────────────────────────────────


class TestPatchServerCoverage:
    @pytest.mark.asyncio
    async def test_patch_gpu_pool_exhausted_restores_old_reservation(
        self, client, admin_token, cov_server, db_session
    ):
        """429 on GPU plan change must restore the old device reservation."""
        new_plan = _make_plan(gpu_limit=2)
        db_session.add(new_plan)
        await db_session.commit()
        await db_session.refresh(new_plan)

        cov_server.status = "running"
        cov_server.container_id = "cid-gpu-patch"
        cov_server.allocated_gpu = 1
        await db_session.commit()

        with (
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
            mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls,
        ):
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=new_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)
            mock_quota_cls.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.release = mock.AsyncMock()
            # First allocate (new plan) fails; second (restore old) succeeds.
            alloc.allocate = mock.AsyncMock(side_effect=[None, ["nvidia.com/gpu=0"]])

            response = await client.patch(
                f"/api/servers/{cov_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(new_plan.id), "reason": "gpu test"},
            )

        assert response.status_code == 429
        assert "No GPUs available" in response.json()["detail"]
        assert alloc.allocate.call_count == 2
        # Restore call re-reserves the old GPU count.
        assert alloc.allocate.call_args_list[1].args[1] == 1

    @pytest.mark.asyncio
    async def test_patch_gpu_reallocation_success(
        self, client, admin_token, cov_server, cov_plan_env, db_session
    ):
        new_plan = _make_plan(gpu_limit=2)
        db_session.add(new_plan)
        await db_session.commit()
        await db_session.refresh(new_plan)

        cov_server.status = "running"
        cov_server.container_id = "cid-gpu-ok"
        cov_server.allocated_gpu = 1
        await db_session.commit()

        with (
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
            mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls,
            mock.patch("app.api.servers.spawner.get_status", return_value="running"),
            mock.patch("app.api.servers.spawner.stop", new=mock.AsyncMock()),
            mock.patch("app.api.servers.spawner.delete", new=mock.AsyncMock()),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result()),
            ),
        ):
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=new_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)
            mock_quota_cls.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.release = mock.AsyncMock()
            alloc.allocate = mock.AsyncMock(
                return_value=["nvidia.com/gpu=0", "nvidia.com/gpu=1"]
            )
            alloc.devices_for = mock.AsyncMock(
                return_value=["nvidia.com/gpu=0", "nvidia.com/gpu=1"]
            )

            response = await client.patch(
                f"/api/servers/{cov_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(new_plan.id), "reason": "gpu test"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["allocated_gpu"] == 2

    @pytest.mark.asyncio
    async def test_patch_volume_mount_marks_home_volume(
        self, client, admin_token, test_user, cov_server, db_session
    ):
        volume = Volume(
            name=_unique("home-vol"),
            display_name="Home Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        with (
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
            mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls,
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result()),
            ),
        ):
            mock_vol = mock_vol_cls.return_value
            mock_vol.check_volumes_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.mark_home_volume = mock.AsyncMock()
            mock_access_cls.return_value.can_access_volume = mock.AsyncMock(return_value=True)

            response = await client.patch(
                f"/api/servers/{cov_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "reason": "home mount test",
                    "volume_mounts": [
                        {
                            "volume_id": str(volume.id),
                            "mount_path": f"/home/{test_user.username}",
                            "mode": "read_write",
                        }
                    ],
                },
            )

        assert response.status_code == 200, f"Response: {response.text}"
        mock_vol.mark_home_volume.assert_called_once_with(str(volume.id))

    @pytest.mark.asyncio
    async def test_patch_recreate_without_environment_uses_dev_fallback(
        self, client, admin_token, cov_server, cov_plan_env, db_session
    ):
        """Respawn with no environment falls back to the 'dev' slug."""
        plan, _ = cov_plan_env
        new_plan = _make_plan()
        db_session.add(new_plan)
        await db_session.commit()
        await db_session.refresh(new_plan)

        cov_server.environment_id = None
        cov_server.container_id = "cid-noenv"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.services.plan_service.PlanService") as mock_plan_cls,
            mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls,
            mock.patch("app.api.servers.spawner.get_status", return_value="running"),
            mock.patch("app.api.servers.spawner.stop", new=mock.AsyncMock()),
            mock.patch("app.api.servers.spawner.delete", new=mock.AsyncMock()),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result()),
            ) as mock_spawn,
        ):
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=new_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)
            mock_quota_cls.return_value.check_spawn_allowed = mock.AsyncMock(
                return_value={"allowed": True}
            )
            response = await client.patch(
                f"/api/servers/{cov_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(new_plan.id), "reason": "no env"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert mock_spawn.call_args.kwargs["environment"] == "dev"
        assert mock_spawn.call_args.kwargs["image"] is None
        assert plan.id != new_plan.id


# ── POST /{id}/test-metric failure ───────────────────────────────────────────


class TestTestMetricCoverage:
    @pytest.mark.asyncio
    async def test_publish_failure_returns_500(
        self, client, user_token, cov_server
    ):
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
    async def test_logs_with_since_param(
        self, client, user_token, test_user, db_session
    ):
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
    async def test_logs_invalid_since_is_ignored(
        self, client, user_token, test_user, db_session
    ):
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
        mock_client.get_container_logs = mock.AsyncMock(
            side_effect=RuntimeError("unexpected")
        )
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

        with mock.patch(
            "app.services.server_auth_service.server_auth_service"
        ) as mock_svc:
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
        assert (
            _admin_server_list_cache_key(1, 10, None, None)
            == "servers:list:admin:1:10:all:all"
        )


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
    async def test_list_serializes_volume_mounts(
        self, client, user_token, test_user, db_session
    ):
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


class TestCreateCleanupPaths:
    @pytest.mark.asyncio
    async def test_spawn_failure_full_cleanup_swallows_errors(
        self, client, user_token, test_user, db_session, cov_plan_env
    ):
        """Failure cleanup tolerates docker/DB cleanup errors (lines 732-735,
        748-752, 768-769)."""
        import contextlib

        plan, env = cov_plan_env

        with _create_stack_mocks(db_session, spawn_side_effect=Exception("boom")) as mocks:
            created_names = []

            async def create_vol_side_effect(*, name, display_name, owner_id, max_size_bytes):
                created_names.append(name)
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

            mocks["volume"].create_volume = mock.AsyncMock(side_effect=create_vol_side_effect)

            @contextlib.asynccontextmanager
            async def _cleanup_session():
                yield db_session

            client_b = mock.AsyncMock()
            client_b.delete_volume = mock.AsyncMock(side_effect=Exception("vol gone"))
            client_c = mock.AsyncMock()
            client_c.delete_container = mock.AsyncMock(side_effect=Exception("gone"))

            with (
                mock.patch(
                    "app.container.client.get_container_client",
                    new=mock.AsyncMock(
                        side_effect=[Exception("no client"), client_b, client_c]
                    ),
                ),
                mock.patch(
                    "app.db.session.async_session",
                    new=mock.Mock(
                        side_effect=[_cleanup_session(), Exception("session boom")]
                    ),
                ),
            ):
                response = await client.post(
                    "/api/servers/",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "name": "cleanup-full-srv",
                        "plan_id": str(plan.id),
                        "environment_id": str(env.id),
                        "volume_mounts": [
                            {"volume_id": "", "mount_path": "/data", "mode": "read_write"},
                            {"volume_id": "", "mount_path": "/extra", "mode": "read_only"},
                        ],
                    },
                )

        assert response.status_code == 500
        assert len(created_names) == 2


class TestStartStopRestartMopUp:
    @pytest.mark.asyncio
    async def test_start_recreate_gpu_ensure_failure_propagates(
        self, client, user_token, cov_server, db_session
    ):
        """HTTPException inside the start try-block re-raises (line 1180)."""
        cov_server.container_id = "cid-ensure-fail"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.api.servers.spawner.get_status", return_value="stopped"),
            mock.patch("app.api.servers.spawner.delete", new=mock.AsyncMock()),
            mock.patch(
                "app.api.servers._ensure_gpu_devices",
                new=mock.AsyncMock(side_effect=HTTPException(status_code=429, detail="no gpu")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_start_no_container_legacy_volume_record_mount(
        self, client, user_token, test_user, cov_server, db_session
    ):
        """Fresh-spawn start records the legacy volume mount (lines 1243-1244)."""
        volume = Volume(
            name=_unique("spawn-legacy-vol"),
            display_name="Spawn Legacy Vol",
            owner_id=test_user.id,
            size_bytes=1000,
        )
        db_session.add(volume)
        await db_session.commit()
        await db_session.refresh(volume)

        cov_server.volume_id = volume.id
        await db_session.commit()

        spawn_result = _mock_spawn_result()
        spawn_result.volume_id = volume.id

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=spawn_result),
            ),
            mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls,
        ):
            mock_vol_cls.return_value.record_mount = mock.AsyncMock()
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        mock_vol_cls.return_value.record_mount.assert_called_once_with(str(volume.id))

    @pytest.mark.asyncio
    async def test_start_no_container_gpu_ensure_failure_propagates(
        self, client, user_token, cov_server
    ):
        """HTTPException in the no-container spawn path re-raises (line 1254)."""
        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch(
                "app.api.servers._ensure_gpu_devices",
                new=mock.AsyncMock(side_effect=HTTPException(status_code=429, detail="no gpu")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/start",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_stop_already_stopped_delete_failure_swallowed(
        self, client, user_token, cov_server, db_session
    ):
        """Stale-container removal failure on already-stopped is tolerated
        (lines 1282-1283)."""
        cov_server.container_id = "cid-stale-stop"
        cov_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.spawner.get_status", return_value="stopped"),
            mock.patch(
                "app.api.servers.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("delete boom")),
            ),
        ):
            response = await client.post(
                f"/api/servers/{cov_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200
        assert "already stopped" in response.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_restart_gpu_delete_failure_swallowed(
        self, client, user_token, cov_server, cov_plan_env, db_session
    ):
        """GPU restart recreate tolerates stale-container delete failure
        (lines 1425-1426)."""
        plan, _ = cov_plan_env
        plan.gpu_limit = 1
        cov_server.container_id = "cid-gpu-restart"
        cov_server.status = "running"
        cov_server.allocated_gpu = 1
        await db_session.commit()

        with (
            mock.patch("app.api.servers.settings.credits_enabled", False),
            mock.patch("app.services.gpu_allocator.GpuAllocatorService") as mock_alloc_cls,
            mock.patch("app.api.servers.spawner.get_status", return_value="paused"),
            mock.patch(
                "app.api.servers.spawner.delete",
                new=mock.AsyncMock(side_effect=Exception("delete boom")),
            ),
            mock.patch(
                "app.api.servers.spawner.spawn",
                new=mock.AsyncMock(return_value=_mock_spawn_result()),
            ),
        ):
            alloc = mock_alloc_cls.return_value
            alloc.enabled = mock.Mock(return_value=True)
            alloc.devices_for = mock.AsyncMock(return_value=["nvidia.com/gpu=0"])

            response = await client.post(
                f"/api/servers/{cov_server.id}/restart",
                headers={"Authorization": f"Bearer {user_token}"},
            )

        assert response.status_code == 200, f"Response: {response.text}"
        assert response.json()["status"] == "running"

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
