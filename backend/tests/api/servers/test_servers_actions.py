"""Tests for server action endpoints (start/stop/restart/delete) with mocked spawner."""

from unittest import mock

import pytest
import pytest_asyncio

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
    async def test_start_server_already_running(
        self, client, user_token, action_server, db_session
    ):
        """Starting already running server should return already running."""
        action_server.container_id = "existing-cid"
        action_server.status = "running"
        await db_session.commit()

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.get_status", return_value="running"):
                response = await client.post(
                    f"/api/servers/{action_server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 200
        data = response.json()
        assert "already running" in data["message"].lower()


class TestServerStartNoContainerBranches:
    """Tests for _perform_server_start when no container_id (lines 946-1017)."""

    @pytest.mark.asyncio
    async def test_perform_server_start_missing_config(
        self, client, user_token, test_user, db_session
    ):
        """Starting server with missing plan_id should return 400."""
        server = Server(
            name="no-plan-srv",
            user_id=test_user.id,
            status="stopped",
            plan_id=None,
            environment_id=None,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            response = await client.post(
                f"/api/servers/{server.id}/start", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 400
        assert "incomplete" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_perform_server_start_env_not_found(
        self, client, user_token, test_user, db_session
    ):
        """Starting server with non-existent environment should return 404."""
        plan = ServerPlan(
            name="start-plan",
            slug="start-plan",
            cpu_limit=1,
            memory_limit="1g",
            is_public=True,
            is_active=True,
            cost_per_hour=0,
            visible_to_roles=["user"],
        )
        db_session.add(plan)
        await db_session.commit()
        await db_session.refresh(plan)

        server = Server(
            name="no-env-srv",
            user_id=test_user.id,
            status="stopped",
            plan_id=plan.id,
            environment_id="00000000-0000-0000-0000-000000000000",
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            response = await client.post(
                f"/api/servers/{server.id}/start", headers={"Authorization": f"Bearer {user_token}"}
            )
        assert response.status_code == 404
        assert "Environment not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_perform_server_start_plan_not_found(
        self, client, user_token, test_user, db_session
    ):
        """Starting server with non-existent plan should return 404."""
        env = EnvironmentTemplate(name="start-env", slug="start-env", image="test:latest")
        db_session.add(env)
        await db_session.commit()
        await db_session.refresh(env)

        server = Server(
            name="no-plan-srv2",
            user_id=test_user.id,
            status="stopped",
            plan_id="00000000-0000-0000-0000-000000000000",
            environment_id=env.id,
        )
        db_session.add(server)
        await db_session.commit()
        await db_session.refresh(server)

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.services.plan_service.PlanService") as mock_plan_cls:
                mock_plan = mock_plan_cls.return_value
                mock_plan.can_user_use_plan = mock.AsyncMock(return_value=True)
                mock_plan.get_by_id = mock.AsyncMock(return_value=None)
                response = await client.post(
                    f"/api/servers/{server.id}/start",
                    headers={"Authorization": f"Bearer {user_token}"},
                )
        assert response.status_code == 404
        assert "Plan not found" in response.json()["detail"]


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

        with mock.patch("app.api.servers.spawner.get_status", return_value="stopped"):
            response = await client.post(
                f"/api/servers/{action_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "already stopped" in data["message"].lower()

    @pytest.mark.asyncio
    async def test_stop_container_unknown(self, client, user_token, action_server, db_session):
        """Stopping server with unknown container status should return already stopped."""
        action_server.container_id = "unknown-cid"
        action_server.status = "running"
        await db_session.commit()

        with mock.patch("app.api.servers.spawner.get_status", return_value="unknown"):
            response = await client.post(
                f"/api/servers/{action_server.id}/stop",
                headers={"Authorization": f"Bearer {user_token}"},
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
                            headers={"Authorization": f"Bearer {user_token}"},
                        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

    @pytest.mark.asyncio
    async def test_restart_server_container_unknown_recreate(
        self, client, user_token, action_server, db_session
    ):
        """Restarting server with unknown container should recreate (lines 1160-1202)."""
        action_server.container_id = "restart-unknown-cid"
        action_server.status = "running"
        await db_session.commit()

        mock_spawn = mock.Mock()
        mock_spawn.container_id = "recreated-cid"
        mock_spawn.image = "test:latest"
        mock_spawn.volume_id = None
        mock_spawn.external_url = "http://recreated"

        with mock.patch("app.api.servers.settings.credits_enabled", False):
            with mock.patch("app.api.servers.spawner.get_status", return_value="unknown"):
                with mock.patch("app.api.servers.spawner.spawn", return_value=mock_spawn):
                    response = await client.post(
                        f"/api/servers/{action_server.id}/restart",
                        headers={"Authorization": f"Bearer {user_token}"},
                    )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "recreated" in data["message"].lower()


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
