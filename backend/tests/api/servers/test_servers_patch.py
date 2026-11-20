# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Comprehensive tests for PATCH /api/servers/{server_id} (update_server)."""

from unittest import mock

import pytest
import pytest_asyncio

from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan
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
            mock_env.can_user_use_env = mock.AsyncMock(return_value=True)

            with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
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

                with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
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
                                        "name": "vol-mount-test",
                                        "reason": "test",
                                        "volume_mounts": [
                                            {
                                                "volume_id": str(patch_volume.id),
                                                "mount_path": "/data",
                                                "mode": "read_write",
                                            }
                                        ],
                                    },
                                )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"


class TestPatchCrossUser:
    """Tests for cross-user server updates."""

    @pytest.mark.asyncio
    async def test_patch_cross_user_with_reason(self, client, admin_token, patch_server):
        """Admin updating another user's server with a reason should succeed."""
        response = await client.patch(
            f"/api/servers/{patch_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "cross-renamed", "reason": "Maintenance update"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "cross-renamed"


class TestPatchServerNameUniqueness:
    """Renames must not collide with the owner's other servers."""

    @pytest.mark.asyncio
    async def test_patch_rename_to_existing_name_rejected(
        self, client, admin_token, patch_server, db_session, test_user
    ):
        """Renaming to a sibling server's name returns 409."""
        sibling = Server(name="sibling-srv", user_id=test_user.id, status="stopped")
        db_session.add(sibling)
        await db_session.commit()

        response = await client.patch(
            f"/api/servers/{patch_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "sibling-srv", "reason": "uniqueness test"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "request_already_exists"

    @pytest.mark.asyncio
    async def test_patch_rename_unique_name_allowed(
        self, client, admin_token, patch_server, db_session, test_user
    ):
        """Renaming to a fresh name works."""
        response = await client.patch(
            f"/api/servers/{patch_server.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "renamed-srv", "reason": "uniqueness test"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "renamed-srv"
