"""Comprehensive tests for PATCH /api/servers/{server_id} (update_server)."""

import pytest
import pytest_asyncio
from unittest import mock
import uuid as uuid_mod

from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate
from app.models.volume import Volume


@pytest_asyncio.fixture
async def patch_server(db_session, test_user):
    """Create a server, plan, and environment for patch tests."""
    plan = ServerPlan(
        name="patch-plan",
        slug="patch-plan",
        cpu_limit=1,
        memory_limit="1g",
        disk_limit="10g",
        is_public=True,
        is_active=True,
        cost_per_hour=0,
        priority=0,
        max_runtime="1h",
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(name="patch-env", slug="patch-env", image="test:latest")
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)
    server = Server(
        name="patch-srv",
        user_id=test_user.id,
        status="stopped",
        plan_id=plan.id,
        environment_id=env.id,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


@pytest_asyncio.fixture
async def patch_volume(db_session, test_user):
    """Create a volume for patch tests."""
    volume = Volume(
        name="patch-vol",
        display_name="Patch Volume",
        owner_id=test_user.id,
        size_bytes=1000,
        max_size_bytes=10737418240,
    )
    db_session.add(volume)
    await db_session.commit()
    await db_session.refresh(volume)
    return volume


def _mock_spawn_return():
    """Return a mock object suitable for spawner.spawn return value."""
    m = mock.Mock()
    m.container_id = "new-cid"
    m.image = "test:latest"
    m.volume_id = None
    m.external_url = "http://test"
    m.allocated_cpu = 1.0
    m.allocated_memory = "1g"
    m.disk_limit = "10g"
    return m


class TestPatchNameChange:
    """Tests for name-only patch (no recreate)."""

    @pytest.mark.asyncio
    async def test_patch_name_change_only(self, client, admin_token, patch_server):
        """Name change should succeed without triggering recreate."""
        response = await client.patch(
            f"/api/servers/{patch_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "renamed-srv", "reason": "test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "renamed-srv"
        assert data["status"] == "stopped"


class TestPatchPlanChange:
    """Tests for plan change paths."""

    @pytest.mark.asyncio
    async def test_patch_plan_change_triggers_recreate(
        self, client, admin_token, patch_server, db_session
    ):
        """Valid plan change should trigger recreate and respawn."""
        new_plan = ServerPlan(
            name="new-patch-plan",
            slug="new-patch-plan",
            cpu_limit=2,
            memory_limit="2g",
            disk_limit="20g",
            is_public=True,
            is_active=True,
            cost_per_hour=0,
            priority=0,
            max_runtime="1h",
            visible_to_roles=["user"],
        )
        db_session.add(new_plan)
        await db_session.commit()
        await db_session.refresh(new_plan)

        patch_server.container_id = "old-cid"
        patch_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=new_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)

            with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
                mock_quota = mock_quota_cls.return_value
                mock_quota.check_spawn_allowed = mock.AsyncMock(
                    return_value={"allowed": True}
                )

                with mock.patch(
                    "app.api.servers.spawner.get_status", return_value="running"
                ):
                    with mock.patch("app.api.servers.spawner.stop", return_value=True):
                        with mock.patch(
                            "app.api.servers.spawner.delete", return_value=True
                        ):
                            with mock.patch(
                                "app.api.servers.spawner.spawn",
                                return_value=_mock_spawn_return(),
                            ):
                                response = await client.patch(
                                    f"/api/servers/{patch_server.id}",
                                    headers={"Authorization": f"Bearer {admin_token}"},
                                    json={"plan_id": str(new_plan.id), "reason": "test"},
                                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["container_id"] == "new-cid"

    @pytest.mark.asyncio
    async def test_patch_plan_not_found(self, client, admin_token, patch_server):
        """Plan not found should return 404."""
        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=None)

            response = await client.patch(
                f"/api/servers/{patch_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": "00000000-0000-0000-0000-000000000000", "reason": "test"},
            )

        assert response.status_code == 404
        assert "Plan not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_patch_plan_not_available_for_role(
        self, client, admin_token, patch_server
    ):
        """Plan not available for role should return 403."""
        fake_plan = mock.Mock()
        fake_plan.id = uuid_mod.uuid4()
        fake_plan.is_active = True

        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=fake_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=False)

            response = await client.patch(
                f"/api/servers/{patch_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(fake_plan.id), "reason": "test"},
            )

        assert response.status_code == 403
        assert "not available" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_patch_plan_inactive(self, client, admin_token, patch_server):
        """Inactive plan should return 400."""
        fake_plan = mock.Mock()
        fake_plan.id = uuid_mod.uuid4()
        fake_plan.is_active = False

        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=fake_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)

            response = await client.patch(
                f"/api/servers/{patch_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"plan_id": str(fake_plan.id), "reason": "test"},
            )

        assert response.status_code == 400
        assert "not active" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_patch_plan_quota_denied(self, client, admin_token, patch_server):
        """Quota denied should return 429."""
        fake_plan = mock.Mock()
        fake_plan.id = uuid_mod.uuid4()
        fake_plan.is_active = True

        with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
            mock_plan = mock_plan_cls.return_value
            mock_plan.get_by_id = mock.AsyncMock(return_value=fake_plan)
            mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)

            with mock.patch("app.services.quota_service.QuotaService") as mock_quota_cls:
                mock_quota = mock_quota_cls.return_value
                mock_quota.check_spawn_allowed = mock.AsyncMock(
                    return_value={"allowed": False, "reason": "quota exceeded"}
                )

                response = await client.patch(
                    f"/api/servers/{patch_server.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"plan_id": str(fake_plan.id), "reason": "test"},
                )

        assert response.status_code == 429
        assert "quota exceeded" in response.json()["detail"].lower()


class TestPatchEnvironmentChange:
    """Tests for environment change paths."""

    @pytest.mark.asyncio
    async def test_patch_environment_change_triggers_recreate(
        self, client, admin_token, patch_server, db_session
    ):
        """Valid environment change should trigger recreate."""
        new_env = EnvironmentTemplate(
            name="new-patch-env", slug="new-patch-env", image="new-image:latest"
        )
        db_session.add(new_env)
        await db_session.commit()
        await db_session.refresh(new_env)

        patch_server.container_id = "old-cid"
        patch_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls:
            mock_env = mock_env_cls.return_value
            mock_env.get_by_id = mock.AsyncMock(return_value=new_env)

            with mock.patch(
                "app.api.servers.spawner.get_status", return_value="running"
            ):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch("app.api.servers.spawner.delete", return_value=True):
                        with mock.patch(
                            "app.api.servers.spawner.spawn",
                            return_value=_mock_spawn_return(),
                        ):
                            response = await client.patch(
                                f"/api/servers/{patch_server.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"environment_id": str(new_env.id), "reason": "test"},
                            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_patch_environment_not_found(self, client, admin_token, patch_server):
        """Environment not found should return 404."""
        with mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls:
            mock_env = mock_env_cls.return_value
            mock_env.get_by_id = mock.AsyncMock(return_value=None)

            response = await client.patch(
                f"/api/servers/{patch_server.id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"environment_id": "00000000-0000-0000-0000-000000000000", "reason": "test"},
            )

        assert response.status_code == 404
        assert "Environment not found" in response.json()["detail"]


class TestPatchVolumeMounts:
    """Tests for volume mount change paths."""

    @pytest.mark.asyncio
    async def test_patch_volume_mounts_change_triggers_recreate(
        self, client, admin_token, patch_server, db_session, patch_volume
    ):
        """Changing volume mounts should trigger recreate."""
        patch_server.container_id = "old-cid"
        patch_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
            mock_vol = mock_vol_cls.return_value
            mock_vol.check_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.check_volumes_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.get_volume = mock.AsyncMock(return_value=patch_volume)
            mock_vol.mark_home_volume = mock.AsyncMock()

            with mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls:
                mock_access = mock_access_cls.return_value
                mock_access.can_access_volume = mock.AsyncMock(return_value=True)

                with mock.patch(
                    "app.api.servers.spawner.get_status", return_value="running"
                ):
                    with mock.patch("app.api.servers.spawner.stop", return_value=True):
                        with mock.patch(
                            "app.api.servers.spawner.delete", return_value=True
                        ):
                            with mock.patch(
                                "app.api.servers.spawner.spawn",
                                return_value=_mock_spawn_return(),
                            ):
                                response = await client.patch(
                                    f"/api/servers/{patch_server.id}",
                                    headers={"Authorization": f"Bearer {admin_token}"},
                                    json={
                                        "name": "vol-mount-test",
                                        "reason": "test",
                                        "volume_mounts": [
                                            {
                                                "volume_id": str(patch_volume.id),
                                                "mount_path": "/data",
                                                "mode": "read_write",
                                            }
                                        ]
                                    },
                                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_patch_volume_mounts_auto_create_volume(
        self, client, admin_token, patch_server, db_session
    ):
        """Empty volume_id should auto-create a volume."""
        patch_server.container_id = "old-cid"
        patch_server.status = "running"
        await db_session.commit()

        auto_vol = Volume(
            name="auto-vol-patch",
            display_name="Auto Volume",
            owner_id=patch_server.user_id,
            size_bytes=1000,
        )
        db_session.add(auto_vol)
        await db_session.commit()
        await db_session.refresh(auto_vol)

        with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
            mock_vol = mock_vol_cls.return_value
            mock_vol.create_volume = mock.AsyncMock(return_value=auto_vol)
            mock_vol.check_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.check_aggregate_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.check_volumes_quota = mock.AsyncMock(return_value={"allowed": True})
            mock_vol.mark_home_volume = mock.AsyncMock()

            with mock.patch(
                "app.api.servers.spawner.get_status", return_value="running"
            ):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch("app.api.servers.spawner.delete", return_value=True):
                        with mock.patch(
                            "app.api.servers.spawner.spawn",
                            return_value=_mock_spawn_return(),
                        ):
                            response = await client.patch(
                                f"/api/servers/{patch_server.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={
                                    "name": "auto-vol-test",
                                    "reason": "test",
                                    "volume_mounts": [
                                        {
                                            "volume_id": "",
                                            "mount_path": "/data",
                                            "mode": "read_write",
                                            "max_size_bytes": 1073741824,
                                        }
                                    ]
                                },
                            )

        assert response.status_code == 200
        mock_vol.create_volume.assert_called_once()

    @pytest.mark.asyncio
    async def test_patch_volume_mounts_access_denied(
        self, client, admin_token, patch_server, patch_volume
    ):
        """Volume access denied should return 403."""
        with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
            mock_vol = mock_vol_cls.return_value
            mock_vol.get_volume = mock.AsyncMock(return_value=patch_volume)

            with mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls:
                mock_access = mock_access_cls.return_value
                mock_access.can_access_volume = mock.AsyncMock(return_value=False)

                response = await client.patch(
                    f"/api/servers/{patch_server.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "reason": "test",
                        "volume_mounts": [
                            {
                                "volume_id": str(patch_volume.id),
                                "mount_path": "/data",
                                "mode": "read_write",
                            }
                        ]
                    },
                )

        assert response.status_code == 403
        assert "cannot be mounted" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_patch_volume_mounts_single_quota_exceeded(
        self, client, admin_token, patch_server, patch_volume
    ):
        """Single volume quota exceeded should return 400."""
        with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
            mock_vol = mock_vol_cls.return_value
            mock_vol.check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": False, "reason": "single quota exceeded"}
            )

            with mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls:
                mock_access = mock_access_cls.return_value
                mock_access.can_access_volume = mock.AsyncMock(return_value=True)

                response = await client.patch(
                    f"/api/servers/{patch_server.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "reason": "test",
                        "volume_mounts": [
                            {
                                "volume_id": str(patch_volume.id),
                                "mount_path": "/data",
                                "mode": "read_write",
                            }
                        ]
                    },
                )

        assert response.status_code == 400
        assert "single quota exceeded" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_patch_volume_mounts_aggregate_quota_exceeded(
        self, client, admin_token, patch_server, patch_volume
    ):
        """Aggregate volume quota exceeded should return 400."""
        with mock.patch("app.services.volume_service.VolumeService") as mock_vol_cls:
            mock_vol = mock_vol_cls.return_value
            mock_vol.check_volumes_quota = mock.AsyncMock(
                return_value={"allowed": False, "reason": "aggregate quota exceeded"}
            )

            with mock.patch(
                "app.services.volume_access_service.VolumeAccessService"
            ) as mock_access_cls:
                mock_access = mock_access_cls.return_value
                mock_access.can_access_volume = mock.AsyncMock(return_value=True)

                response = await client.patch(
                    f"/api/servers/{patch_server.id}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={
                        "reason": "test",
                        "volume_mounts": [
                            {
                                "volume_id": str(patch_volume.id),
                                "mount_path": "/data",
                                "mode": "read_write",
                            }
                        ]
                    },
                )

        assert response.status_code == 400
        assert "aggregate quota exceeded" in response.json()["detail"].lower()


class TestPatchRecreate:
    """Tests for container recreate during patch."""

    @pytest.mark.asyncio
    async def test_patch_recreate_running_container_stop_delete_called(
        self, client, admin_token, patch_server, db_session
    ):
        """Recreate with running container should call spawner.stop and spawner.delete."""
        new_env = EnvironmentTemplate(
            name="recreate-env", slug="recreate-env", image="recreate:latest"
        )
        db_session.add(new_env)
        await db_session.commit()
        await db_session.refresh(new_env)

        patch_server.container_id = "running-cid-2"
        patch_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls:
            mock_env = mock_env_cls.return_value
            mock_env.get_by_id = mock.AsyncMock(return_value=new_env)

            with mock.patch(
                "app.api.servers.spawner.get_status", return_value="running"
            ):
                with mock.patch(
                    "app.api.servers.spawner.stop", return_value=True
                ) as mock_stop2:
                    with mock.patch(
                        "app.api.servers.spawner.delete", return_value=True
                    ) as mock_delete2:
                        with mock.patch(
                            "app.api.servers.spawner.spawn",
                            return_value=_mock_spawn_return(),
                        ):
                            response = await client.patch(
                                f"/api/servers/{patch_server.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"environment_id": str(new_env.id), "reason": "test"},
                            )

        assert response.status_code == 200
        mock_stop2.assert_called_once_with("running-cid-2")
        mock_delete2.assert_called_once_with("running-cid-2")

    @pytest.mark.asyncio
    async def test_patch_recreate_spawn_success(
        self, client, admin_token, patch_server, db_session
    ):
        """Recreate spawn success should set status=running and new container_id."""
        new_env = EnvironmentTemplate(
            name="success-env", slug="success-env", image="success:latest"
        )
        db_session.add(new_env)
        await db_session.commit()
        await db_session.refresh(new_env)

        patch_server.container_id = "old-cid-success"
        patch_server.status = "running"
        await db_session.commit()

        mock_spawn_result = _mock_spawn_return()
        mock_spawn_result.container_id = "respawned-cid"
        mock_spawn_result.external_url = "http://respawned"

        with mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls:
            mock_env = mock_env_cls.return_value
            mock_env.get_by_id = mock.AsyncMock(return_value=new_env)

            with mock.patch(
                "app.api.servers.spawner.get_status", return_value="running"
            ):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch(
                        "app.api.servers.spawner.delete", return_value=True
                    ):
                        with mock.patch(
                            "app.api.servers.spawner.spawn",
                            return_value=mock_spawn_result,
                        ):
                            response = await client.patch(
                                f"/api/servers/{patch_server.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"environment_id": str(new_env.id), "reason": "test"},
                            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert data["container_id"] == "respawned-cid"
        assert data["external_url"] == "http://respawned"

    @pytest.mark.asyncio
    async def test_patch_recreate_spawn_failure(
        self, client, admin_token, patch_server, db_session
    ):
        """Recreate spawn failure should return 500 with proper error message."""
        new_env = EnvironmentTemplate(
            name="fail-env", slug="fail-env", image="fail:latest"
        )
        db_session.add(new_env)
        await db_session.commit()
        await db_session.refresh(new_env)

        patch_server.container_id = "old-cid-fail"
        patch_server.status = "running"
        await db_session.commit()

        with mock.patch("app.services.environment_service.EnvironmentService") as mock_env_cls:
            mock_env = mock_env_cls.return_value
            mock_env.get_by_id = mock.AsyncMock(return_value=new_env)

            with mock.patch(
                "app.api.servers.spawner.get_status", return_value="running"
            ):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch(
                        "app.api.servers.spawner.delete", return_value=True
                    ):
                        with mock.patch(
                            "app.api.servers.spawner.spawn",
                            side_effect=Exception("spawn failed"),
                        ):
                            response = await client.patch(
                                f"/api/servers/{patch_server.id}",
                                headers={"Authorization": f"Bearer {admin_token}"},
                                json={"environment_id": str(new_env.id), "reason": "test"},
                            )

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "try again" in detail.lower() or "contact support" in detail.lower()


class TestPatchCrossUser:
    """Tests for cross-user server updates."""

    @pytest.mark.asyncio
    async def test_patch_cross_user_with_reason(
        self, client, admin_token, patch_server
    ):
        """Admin updating another user's server with a reason should succeed."""
        response = await client.patch(
            f"/api/servers/{patch_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "cross-renamed", "reason": "Maintenance update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "cross-renamed"
