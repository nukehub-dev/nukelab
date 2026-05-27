"""Tests for server action endpoints (start/stop/restart/delete) with mocked spawner."""

import pytest
import pytest_asyncio
from unittest import mock

from app.models.server import Server
from app.models.server_plan import ServerPlan
from app.models.environment_template import EnvironmentTemplate


@pytest_asyncio.fixture
async def action_server(db_session, test_user):
    """Create a server with plan and environment for action tests."""
    plan = ServerPlan(
        name="action-plan", slug="action-plan",
        cpu_limit=1, memory_limit="1g", disk_limit="10g",
        is_public=True, is_active=True, cost_per_hour=0
    )
    env = EnvironmentTemplate(name="action-env", slug="action-env", image="test:latest")
    db_session.add_all([plan, env])
    await db_session.commit()
    await db_session.refresh(plan)
    await db_session.refresh(env)

    server = Server(
        name="action-srv", user_id=test_user.id, status="stopped",
        plan_id=plan.id, environment_id=env.id
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
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_server_already_running(self, client, user_token, action_server, db_session):
        """Starting already running server should return already running."""
        action_server.container_id = "existing-cid"
        action_server.status = "running"
        await db_session.commit()

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
                response = await client.post(
                    f"/api/servers/{action_server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
        data = response.json()
        assert "already running" in data["message"].lower()


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
                    headers={"Authorization": f"Bearer {user_token}"}
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

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            response = await client.post(
                f"/api/servers/{action_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 200
        data = response.json()
        assert "already stopped" in data["message"].lower()


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
                            headers={"Authorization": f"Bearer {user_token}"}
                        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"


class TestServerDelete:
    """Tests for server delete endpoint."""

    @pytest.mark.asyncio
    async def test_delete_server_with_container(self, client, user_token, action_server, db_session):
        """Deleting server with container should delete container first."""
        action_server.container_id = "del-cid"
        action_server.status = "stopped"
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            with mock.patch("app.api.servers.spawner.delete", return_value=True):
                response = await client.delete(
                    f"/api/servers/{action_server.id}",
                    headers={"Authorization": f"Bearer {user_token}"}
                )
        assert response.status_code == 200
