# SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for server action endpoints (start/stop/restart/delete) with mocked spawner."""

from datetime import UTC, datetime, timedelta
from unittest import mock

import pytest
import pytest_asyncio

from app.config import settings
from app.models.environment_template import EnvironmentTemplate
from app.models.server import Server
from app.models.server_plan import ServerPlan


@pytest_asyncio.fixture
async def action_server(db_session, test_user):
    """Create a server with plan and environment for action tests."""
    plan = ServerPlan(
        name="action-plan",
        slug="action-plan",
        cpu_limit=1,
        memory_limit="1g",
        disk_limit="10g",
        is_public=True,
        is_active=True,
        cost_per_hour=0,
        visible_to_roles=["user"],
    )
    env = EnvironmentTemplate(name="action-env", slug="action-env", image="test:latest")
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)

    server = Server(
        name="action-srv",
        user_id=test_user.id,
        status="stopped",
        plan_id=plan.id,
        environment_id=env.id,
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


class TestServerStart:
    """Tests for server start endpoint."""

    @pytest.mark.asyncio
    async def test_start_server_no_container_spawns(self, client, user_token, action_server):
        """Starting server without container_id should spawn a new container."""
        with mock.patch("app.api.servers.settings.credits_enabled", False):
            mock_spawn = mock.AsyncMock()
            mock_spawn.container_id = "new-cid"
            mock_spawn.image = "test:latest"
            mock_spawn.volume_id = None
            mock_spawn.external_url = "http://test"
            mock_spawn.allocated_cpu = 1.0
            mock_spawn.allocated_memory = "1g"

            with mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn):
                response = await client.post(
                    f"/api/servers/{action_server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_server_sets_expires_at(
        self, client, user_token, action_server, db_session
    ):
        """Starting a stopped server should set expires_at from user preferences."""
        action_server.status = "stopped"
        action_server.container_id = None
        action_server.expires_at = None
        await db_session.commit()

        mock_spawn = mock.AsyncMock()
        mock_spawn.container_id = "new-cid"
        mock_spawn.image = "test:latest"
        mock_spawn.volume_id = None
        mock_spawn.external_url = "http://test"
        mock_spawn.allocated_cpu = 1.0
        mock_spawn.allocated_memory = "1g"

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn):
                response = await client.post(
                    f"/api/servers/{action_server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200

        await db_session.refresh(action_server)
        assert action_server.expires_at is not None
        expected = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=settings.server_max_runtime
        )
        assert abs((action_server.expires_at - expected).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_start_server_disabled_runtime_limit_clears_expires_at(
        self, client, user_token, action_server, db_session
    ):
        """Starting a server when max_server_runtime is disabled should not set expires_at."""
        from app.models.user import User

        user = await db_session.get(User, action_server.user_id)
        user.preferences = {"max_server_runtime_enabled": False}
        await db_session.commit()

        action_server.status = "stopped"
        action_server.container_id = None
        action_server.expires_at = None
        await db_session.commit()

        mock_spawn = mock.AsyncMock()
        mock_spawn.container_id = "new-cid"
        mock_spawn.image = "test:latest"
        mock_spawn.volume_id = None
        mock_spawn.external_url = "http://test"
        mock_spawn.allocated_cpu = 1.0
        mock_spawn.allocated_memory = "1g"

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn):
                response = await client.post(
                    f"/api/servers/{action_server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200

        await db_session.refresh(action_server)
        assert action_server.expires_at is None


class TestServerStop:
    """Tests for server stop endpoint."""

    @pytest.mark.asyncio
    async def test_stop_running_server(self, client, user_token, action_server, db_session):
        """Stopping running server should delete container."""
        action_server.container_id = "stop-cid"
        action_server.status = "running"
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                response = await client.post(
                    f"/api/servers/{action_server.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_stop_already_stopped(self, client, user_token, action_server, db_session):
        """Stopping already stopped server should return already stopped."""
        action_server.container_id = "already-stopped-cid"
        action_server.status = "running"
        await db_session.commit()

        with (
            mock.patch("app.api.servers.spawner.get_status", return_value="stopped"),
            mock.patch("app.api.servers.spawner.delete", return_value=True),
        ):
            response = await client.post(
                f"/api/servers/{action_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "stopped" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_stop_server_clears_expires_at(
        self, client, user_token, action_server, db_session
    ):
        """Stopping a running server should clear expires_at."""
        action_server.container_id = "stop-cid"
        action_server.status = "running"
        action_server.expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                response = await client.post(
                    f"/api/servers/{action_server.id}/stop",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200

        await db_session.refresh(action_server)
        assert action_server.expires_at is None


class TestServerRestart:
    """Tests for server restart endpoint."""

    @pytest.mark.asyncio
    async def test_restart_running_server(self, client, user_token, action_server, db_session):
        """Restarting running server should stop and start."""
        action_server.container_id = "restart-cid"
        action_server.status = "running"
        await db_session.commit()

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch("app.api.servers.spawner.start", return_value=True):
                        response = await client.post(
                            f"/api/servers/{action_server.id}/restart",
                            headers={"Authorization": f"Bearer {user_token}"},
                        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_restart_server_resets_expires_at(
        self, client, user_token, action_server, db_session
    ):
        """Restarting a running server should reset expires_at from user preferences."""
        action_server.container_id = "restart-cid"
        action_server.status = "running"
        action_server.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=5)
        await db_session.commit()

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
                with mock.patch("app.api.servers.spawner.stop", return_value=True):
                    with mock.patch("app.api.servers.spawner.start", return_value=True):
                        response = await client.post(
                            f"/api/servers/{action_server.id}/restart",
                            headers={"Authorization": f"Bearer {user_token}"},
                        )
        assert response.status_code == 200

        await db_session.refresh(action_server)
        assert action_server.expires_at is not None
        expected = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            seconds=settings.server_max_runtime
        )
        assert abs((action_server.expires_at - expected).total_seconds()) < 5


class TestServerDelete:
    """Tests for server delete endpoint."""

    @pytest.mark.asyncio
    async def test_delete_server_with_container(
        self, client, user_token, action_server, db_session
    ):
        """Deleting server with container should delete container first."""
        action_server.container_id = "del-cid"
        action_server.status = "stopped"
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                response = await client.delete(
                    f"/api/servers/{action_server.id}",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200
